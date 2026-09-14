# services/aggregates_service.py
"""
Пересчёт таблиц агрегатов аналитики (TODO №1 — переход с мат.view на таблицы).

recompute_supplier_agg()    — supplier_reports → supplier_reports_agg
                              (SQL = тело бывшей MV 01; месяц строки —
                              generated-колонка supplier_reports.period_month);
recompute_product_margins() — supplier_reports_agg → product_margins
                              (SQL = тело бывшей MV 05: nm_id через products,
                              распределение фактической рекламы из
                              mv_wb_ad_actual_expense_by_nm_month).

Единица работы: ОДИН тенант × N месяцев (обычно 1–3) — скан сырья за окно
(десятки–сотни мс) + перегруппировка (мс). months=None → все месяцы тенанта
(полный пересчёт, единицы секунд).

Себестоимость и налог ВШИТЫ в supplier_reports_agg на шаге 1 (джойны
product_costs LATERAL и tax_rates по sale_dt), поэтому при их изменении
пересчитывать нужно СНАЧАЛА agg, ЗАТЕМ product_margins — строго в этом порядке.

Параллельные пересчёты одного тенанта (например, ежедневная реклама в 07:00
и правка налоговой ставки в 07:00:05) сериализуются pg_advisory_xact_lock:
второй ждёт на первой строке транзакции; разные тенанты не блокируют друг
друга. Снимается автоматически при коммите/откате.
"""
import logging
from datetime import date
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Месяц строки берётся из generated-колонки supplier_reports.period_month
# (DDL: db/scripts/03_*.sql) — БД считает её при вставке/обновлении, и под
# фильтр по месяцам работает обычный индекс (tenant_id, period_month).

# --- Тело бывшей MV supplier_reports_agg_mv (db/materialized_views/01_*.sql) ---
AGG_INSERT_SQL_TEMPLATE = """
INSERT INTO supplier_reports_agg (
    tenant_id, period_day, period_week, period_month, period_quarter, period_year,
    product_name, sku,
    quantity_sold, revenue, seller_payout, retail_price_max,
    storage_fee, regular_deduction, dzhem_deduction, delivery_rub, penalty,
    acceptance, return_quantity, return_revenue,
    tax, payout_after_tax, cost_per_unit, total_cost, margin
)
SELECT sr.tenant_id,
    (date_trunc('day'::text, sr.sale_dt::timestamp))::date AS period_day,
    (date_trunc('week'::text, sr.sale_dt::timestamp))::date AS period_week,
    sr.period_month,
    (date_trunc('quarter'::text, sr.sale_dt::timestamp))::date AS period_quarter,
    (date_trunc('year'::text, sr.sale_dt::timestamp))::date AS period_year,
    CASE
        WHEN sr.sku::text = '' OR sr.sku IS NULL THEN '#-=Technical field=-#'
        ELSE p.name
    END AS product_name,
    CASE
        WHEN sr.sku::text = '' OR sr.sku IS NULL THEN ''
        ELSE sr.sku
    END AS sku,
    sum(CASE WHEN sr.sku::text = '' OR sr.sku IS NULL THEN 0
             WHEN sr.doc_type_name::text <> 'Продажа' THEN 0
             ELSE sr.quantity END) AS quantity_sold,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Продажа' THEN sr.retail_amount
             ELSE 0 END) AS revenue,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Продажа' THEN sr.amount_for_pay
             ELSE 0 END) AS seller_payout,
    max(sr.retail_price) AS retail_price_max,
    sum(sr.storage_fee) AS storage_fee,
    sum(CASE WHEN sr.bonus_type_name ~~* '%джем%' OR sr.bonus_type_name ~~* '%dzhem%'
             THEN 0 ELSE sr.deduction END) AS regular_deduction,
    sum(CASE WHEN sr.bonus_type_name ~~* '%джем%' OR sr.bonus_type_name ~~* '%dzhem%'
             THEN sr.deduction ELSE 0 END) AS dzhem_deduction,
    sum(sr.delivery_rub) AS delivery_rub,
    sum(sr.penalty) AS penalty,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Платная приемка' THEN sr.acceptance
             ELSE 0 END) AS acceptance,
    sum(CASE WHEN sr.sku::text = '' OR sr.sku IS NULL THEN 0
             WHEN sr.doc_type_name::text <> 'Возврат' THEN 0
             ELSE sr.quantity END) AS return_quantity,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Возврат' THEN sr.retail_amount
             ELSE 0 END) AS return_revenue,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Продажа'
             THEN sr.retail_amount * tr.tax_rate / 100 ELSE 0 END) AS tax,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Продажа'
             THEN sr.amount_for_pay - sr.retail_amount * tr.tax_rate / 100
             ELSE 0 END) AS payout_after_tax,
    max(COALESCE(pc.cost, 0)) AS cost_per_unit,
    sum(CASE WHEN sr.sku::text = '' OR sr.sku IS NULL THEN 0
             WHEN sr.doc_type_name::text <> 'Продажа' THEN 0
             ELSE sr.quantity END)::numeric * max(COALESCE(pc.cost, 0)) AS total_cost,
    sum(CASE WHEN sr.supplier_oper_name::text = 'Продажа'
             THEN sr.amount_for_pay - sr.retail_amount * tr.tax_rate / 100 ELSE 0 END)
      - sum(CASE WHEN sr.sku::text = '' OR sr.sku IS NULL THEN 0
                 WHEN sr.doc_type_name::text <> 'Продажа' THEN 0
                 ELSE sr.quantity END)::numeric * max(COALESCE(pc.cost, 0))
      - sum(sr.delivery_rub) - sum(sr.penalty)
      - sum(CASE WHEN sr.supplier_oper_name::text = 'Платная приемка' THEN sr.acceptance ELSE 0 END)
      - sum(CASE WHEN sr.supplier_oper_name::text = 'Возврат' THEN sr.retail_amount ELSE 0 END)
      AS margin
FROM supplier_reports sr
    LEFT JOIN tax_rates tr
        ON tr.tenant_id = sr.tenant_id
       AND sr.sale_dt >= tr.start_date
       AND sr.sale_dt <= COALESCE(tr.end_date, '9999-01-01'::date)
    LEFT JOIN products p
        ON p.sku::text = sr.sku::text AND p.tenant_id = sr.tenant_id
    LEFT JOIN LATERAL (
        SELECT pc_1.cost
        FROM product_costs pc_1
        WHERE pc_1.product_id = p.id
          AND pc_1.start_date <= COALESCE(sr.sale_dt::timestamp, CURRENT_DATE::timestamp)
          AND (pc_1.end_date IS NULL OR pc_1.end_date >= COALESCE(sr.sale_dt::timestamp, CURRENT_DATE::timestamp))
        ORDER BY pc_1.start_date DESC
        LIMIT 1
    ) pc ON true
WHERE sr.tenant_id = :tenant_id
  {months_filter}
GROUP BY sr.tenant_id,
    (date_trunc('day'::text, sr.sale_dt::timestamp)),
    (date_trunc('week'::text, sr.sale_dt::timestamp)),
    sr.period_month,
    (date_trunc('quarter'::text, sr.sale_dt::timestamp)),
    (date_trunc('year'::text, sr.sale_dt::timestamp)),
    p.name, sr.sku
"""

# --- Тело бывшей MV product_margins_mv (db/materialized_views/05_*.sql) ---
MARGINS_INSERT_SQL_TEMPLATE = """
INSERT INTO product_margins (
    tenant_id, period_month, product_name, sku, nm_id,
    quantity_sold, revenue, seller_payout, retail_price_max,
    tax, payout_after_tax, cost_per_unit, total_cost,
    storage_fee, regular_deduction, dzhem_deduction, delivery_rub, penalty,
    acceptance, return_quantity, return_revenue, margin,
    margin_percent_revenue, margin_percent_payout, logistics_per_unit, margin_per_unit,
    actual_ad_expense_amount, campaigns_count, advertising_days_count,
    factual_drr_percent, margin_after_advertising
)
WITH margins AS (
    SELECT p.tenant_id,
        p.period_month,
        p.product_name,
        p.sku,
        sum(p.quantity_sold) AS quantity_sold,
        sum(p.revenue) AS revenue,
        sum(p.seller_payout) AS seller_payout,
        max(p.retail_price_max) AS retail_price_max,
        sum(p.tax) AS tax,
        sum(p.payout_after_tax) AS payout_after_tax,
        max(p.cost_per_unit) AS cost_per_unit,
        sum(p.total_cost) AS total_cost,
        sum(p.storage_fee) AS storage_fee,
        sum(p.regular_deduction) AS regular_deduction,
        sum(p.dzhem_deduction) AS dzhem_deduction,
        sum(p.delivery_rub) AS delivery_rub,
        sum(p.penalty) AS penalty,
        sum(p.acceptance) AS acceptance,
        sum(p.return_quantity) AS return_quantity,
        sum(p.return_revenue) AS return_revenue,
        sum(p.margin) AS margin,
        CASE WHEN sum(p.revenue) = 0 THEN 0
             ELSE sum(p.margin) / sum(p.revenue) * 100 END AS margin_percent_revenue,
        CASE WHEN sum(p.seller_payout) = 0 THEN 0
             ELSE sum(p.margin) / sum(p.seller_payout) * 100 END AS margin_percent_payout,
        CASE WHEN sum(p.quantity_sold) = 0 THEN 0
             ELSE sum(p.delivery_rub) / sum(p.quantity_sold) END AS logistics_per_unit,
        CASE WHEN sum(p.quantity_sold) = 0 THEN 0
             ELSE sum(p.margin) / sum(p.quantity_sold) END AS margin_per_unit
    FROM supplier_reports_agg p
    WHERE p.tenant_id = :tenant_id
      {months_filter}
    GROUP BY p.tenant_id, p.period_month, p.product_name, p.sku
),
with_nm AS (
    -- nmId карточки: products.marketplace_sku, безопасный каст в bigint
    -- (мусорные значения ручных товаров → NULL, реклама просто не joinится)
    SELECT m.*,
           CASE WHEN btrim(pr.marketplace_sku) ~ '^[0-9]+$'
                THEN btrim(pr.marketplace_sku)::bigint
                ELSE NULL::bigint END AS nm_id
    FROM margins m
    LEFT JOIN products pr
        ON pr.tenant_id = m.tenant_id AND pr.sku::text = m.sku::text
),
with_ad AS (
    SELECT w.*,
           ad.allocated_actual_ad_expense_amount,
           ad.campaigns_count,
           ad.advertising_days_count
    FROM with_nm w
    LEFT JOIN mv_wb_ad_actual_expense_by_nm_month ad
        ON ad.tenant_id = w.tenant_id
       AND ad.expense_month_msk = w.period_month
       AND ad.nm_id = w.nm_id
       AND ad.currency = 'RUB'
),
split_base AS (
    SELECT a.*,
           sum(a.revenue) OVER (PARTITION BY a.tenant_id, a.period_month, a.nm_id) AS nm_revenue_total,
           row_number() OVER (PARTITION BY a.tenant_id, a.period_month, a.nm_id ORDER BY a.sku) AS rn,
           count(*) OVER (PARTITION BY a.tenant_id, a.period_month, a.nm_id) AS sku_count
    FROM with_ad a
),
ad_split AS (
    -- Расход карточки НЕ дублируется на каждый sku-дубль, а распределяется
    -- пропорционально выручке; последний sku (по sku) — остаток копеек.
    SELECT s.*,
           CASE
               WHEN s.allocated_actual_ad_expense_amount IS NULL THEN NULL::numeric
               WHEN s.sku_count = 1 THEN s.allocated_actual_ad_expense_amount
               WHEN s.nm_revenue_total > 0 THEN
                   CASE WHEN s.rn < s.sku_count THEN
                            round(s.allocated_actual_ad_expense_amount * s.revenue
                                  / s.nm_revenue_total, 2)
                        ELSE s.allocated_actual_ad_expense_amount - coalesce(sum(
                                 round(s.allocated_actual_ad_expense_amount * s.revenue
                                       / s.nm_revenue_total, 2)
                             ) FILTER (WHERE s.rn < s.sku_count) OVER (
                                 PARTITION BY s.tenant_id, s.period_month, s.nm_id), 0::numeric)
                   END
               ELSE
                   CASE WHEN s.rn < s.sku_count THEN
                            round(s.allocated_actual_ad_expense_amount / s.sku_count, 2)
                        ELSE s.allocated_actual_ad_expense_amount - coalesce(sum(
                                 round(s.allocated_actual_ad_expense_amount / s.sku_count, 2)
                             ) FILTER (WHERE s.rn < s.sku_count) OVER (
                                 PARTITION BY s.tenant_id, s.period_month, s.nm_id), 0::numeric)
                   END
           END AS split_ad_amount
    FROM split_base s
)
SELECT d.tenant_id,
    d.period_month,
    d.product_name,
    d.sku,
    d.nm_id,
    d.quantity_sold,
    d.revenue,
    d.seller_payout,
    d.retail_price_max,
    d.tax,
    d.payout_after_tax,
    d.cost_per_unit,
    d.total_cost,
    d.storage_fee,
    d.regular_deduction,
    d.dzhem_deduction,
    d.delivery_rub,
    d.penalty,
    d.acceptance,
    d.return_quantity,
    d.return_revenue,
    d.margin,
    d.margin_percent_revenue,
    d.margin_percent_payout,
    d.logistics_per_unit,
    d.margin_per_unit,
    coalesce(d.split_ad_amount, 0::numeric) AS actual_ad_expense_amount,
    coalesce(d.campaigns_count, 0) AS campaigns_count,
    coalesce(d.advertising_days_count, 0) AS advertising_days_count,
    CASE WHEN d.revenue > 0
         THEN round(coalesce(d.split_ad_amount, 0::numeric) / d.revenue * 100::numeric, 2)
         ELSE NULL::numeric END AS factual_drr_percent,
    d.margin - coalesce(d.split_ad_amount, 0::numeric) AS margin_after_advertising
FROM ad_split d
"""


def months_in_range(date_from: date, date_to: date) -> List[date]:
    """Первые числа месяцев, покрывающих диапазон [date_from, date_to]."""
    months = []
    current = date(date_from.year, date_from.month, 1)
    last = date(date_to.year, date_to.month, 1)
    while current <= last:
        months.append(current)
        current = date(current.year + (current.month // 12), (current.month % 12) + 1, 1)
    return months


def _take_advisory_lock(db: Session, tenant_id: int):
    """Сериализация пересчётов одного тенанта (см. docstring модуля).

    xact-вариант: держится до коммта/отката текущей транзакции сессии.
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"recompute:{tenant_id}"},
    )


def _months_clause(months: Optional[List[date]]) -> str:
    return "AND period_month IN :months" if months else ""



def _expand_months(stmt, months):
    """Для text()-запросов с :months (expanding-список дат)."""
    if months:
        from sqlalchemy import bindparam
        stmt = stmt.bindparams(bindparam("months", expanding=True))
    return stmt

def _months_clause_for_source(alias: str, months: Optional[List[date]]) -> str:
    if not months:
        return "AND 1 = 1"
    return f"AND {alias}.period_month IN :months"


def recompute_supplier_agg(db: Session, tenant_id: int, months: Optional[List[date]] = None) -> int:
    """Пересчитать supplier_reports_agg тенанта за месяцы (None = все месяцы).

    DELETE месяцев + INSERT...SELECT из supplier_reports. Сам коммитит:
    вызывать ПОСЛЕ коммита собственных изменений (сырых строк, ставок и т.д.).
    Возвращает число вставленных строк agg.
    """
    import time

    start = time.time()
    try:
        _take_advisory_lock(db, tenant_id)

        delete_sql = "DELETE FROM supplier_reports_agg WHERE tenant_id = :tenant_id"
        params = {"tenant_id": tenant_id}
        if months:
            delete_sql += " AND period_month IN :months"
            params["months"] = list(months)
        db.execute(_expand_months(text(delete_sql), months), params)

        insert_sql = AGG_INSERT_SQL_TEMPLATE.format(
            months_filter=_months_clause_for_source("sr", months),
        )
        exec_params = {"tenant_id": tenant_id}
        stmt = _expand_months(text(insert_sql), months)
        if months:
            exec_params["months"] = list(months)
        result = db.execute(stmt, exec_params)

        db.commit()
        inserted = result.rowcount or 0
        elapsed = int((time.time() - start) * 1000)
        logger.info(
            f"✅ supplier_reports_agg recomputed | tenant={tenant_id} | "
            f"months={len(months) if months else 'ALL'} | rows={inserted} | {elapsed}ms"
        )
        return inserted

    except Exception as e:
        db.rollback()
        logger.error(f"❌ supplier_reports_agg recompute failed | tenant={tenant_id}: {e}")
        raise


def recompute_product_margins(db: Session, tenant_id: int, months: Optional[List[date]] = None) -> int:
    """Пересчитать product_margins тенанта за месяцы (None = все месяцы).

    Источник: supplier_reports_agg (сначала recompute_supplier_agg!) + products
    + mv_wb_ad_actual_expense_by_nm_month (рекламные MV остаются mat.view).
    Сам коммитит. Возвращает число вставленных строк.
    """
    import time

    start = time.time()
    try:
        _take_advisory_lock(db, tenant_id)

        delete_sql = "DELETE FROM product_margins WHERE tenant_id = :tenant_id"
        params = {"tenant_id": tenant_id}
        if months:
            delete_sql += " AND period_month IN :months"
            params["months"] = list(months)
        db.execute(_expand_months(text(delete_sql), months), params)

        insert_sql = MARGINS_INSERT_SQL_TEMPLATE.format(
            months_filter=_months_clause_for_source("p", months),
        )
        exec_params = {"tenant_id": tenant_id}
        stmt = _expand_months(text(insert_sql), months)
        if months:
            exec_params["months"] = list(months)
        result = db.execute(stmt, exec_params)

        db.commit()
        inserted = result.rowcount or 0
        elapsed = int((time.time() - start) * 1000)
        logger.info(
            f"✅ product_margins recomputed | tenant={tenant_id} | "
            f"months={len(months) if months else 'ALL'} | rows={inserted} | {elapsed}ms"
        )
        return inserted

    except Exception as e:
        db.rollback()
        logger.error(f"❌ product_margins recompute failed | tenant={tenant_id}: {e}")
        raise


def recompute_analytics(db: Session, tenant_id: int, months: Optional[List[date]] = None) -> dict:
    """Полный пересчёт цепочки: agg → product_margins (строго в этом порядке)."""
    agg_rows = recompute_supplier_agg(db, tenant_id, months)
    margins_rows = recompute_product_margins(db, tenant_id, months)
    return {"agg_rows": agg_rows, "margins_rows": margins_rows,
            "months": sorted(m.isoformat() for m in months) if months else "ALL"}
