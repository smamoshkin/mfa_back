-- 05_create_product_margins_mv.sql
-- ============================================================================
-- Помесячная материализованная view — источник для отчёта рентабельности
-- (AnalyticsService._get_aggregated_data) и оборачиваемости.
--
-- Логика GROUP BY и все вычисляемые показатели (margin_percent_revenue,
-- margin_per_unit, logistics_per_unit и т.д.) перенесены из
-- db/views/product_margins_month_v.sql БЕЗ ИЗМЕНЕНИЙ (CTE margins).
--
-- ДОРАБОТКА 2026-09: фактические рекламные расходы (WB /adv/v1/upd,
-- аллоцированные на nmId через /adv/v3/fullstats — см. MV 03/04).
-- Существующая финансовая логика НЕ менялась, только добавлены поля:
--   nm_id                  — nmId WB (products.marketplace_sku; безопасный
--                            каст varchar→bigint, мусорные значения → NULL)
--   actual_ad_expense_amount       — COALESCE(аллоцированный расход, 0)
--   campaigns_count / advertising_days_count — из месячной рекламной MV
--   factual_drr_percent    — расход / выручка * 100; NULL при выручке <= 0
--   margin_after_advertising — маржа минус рекламный расход (старые колонки
--                            маржи не тронуты — реклама в них не входила)
--
-- Соединение с рекламой: tenant_id + period_month + nm_id + currency='RUB'.
-- Ключ связи именно nmId (marketplace_sku), НЕ sku: товар продавца (sku)
-- однозначно отображается в карточку WB (nm_id) через products.
--
-- ДУБЛИ sku → один nmId (переименование артикула продавца: старый sku
-- деактивируется, но его история продаж остаётся; в переходном месяце у
-- карточки два sku с продажами). Расход карточки НЕ дублируется на каждый
-- sku, а РАСПРЕДЕЛЯЕТСЯ между ними пропорционально выручке месяца
-- (последний sku по алфавиту — остаток в копейках; при нулевой выручке у
-- всех — поровну). Инвариант: Σ actual_ad_expense_amount по месяце =
-- allocated_actual_ad_expense_amount из рекламной MV, до копейки.
--
-- Уникальность строк сохранена: (tenant_id, period_month, sku) из GROUP BY,
-- оба LEFT JOIN — к ключам с уникальными индексами (products.uq(tenant,sku),
-- mv_wb_ad_actual_expense_by_nm_month_uq), размножения строк нет.
--
-- ВАЖНО: применять строго после 01 (supplier_reports_agg_mv), 03 и 04
-- (рекламные MV) — порядок нумерации файлов = порядок применения.
--
-- period_month берётся напрямую из supplier_reports_agg_mv (без
-- дополнительного date_trunc), тип наследуется от источника (date).
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS public.product_margins_mv;

CREATE MATERIALIZED VIEW public.product_margins_mv
AS
WITH margins AS (
    -- === существующая агрегация (до доработки) — без изменений ===
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
            CASE
                WHEN sum(p.revenue) = 0::numeric THEN 0::numeric
                ELSE sum(p.margin) / sum(p.revenue) * 100::numeric
            END AS margin_percent_revenue,
            CASE
                WHEN sum(p.seller_payout) = 0::numeric THEN 0::numeric
                ELSE sum(p.margin) / sum(p.seller_payout) * 100::numeric
            END AS margin_percent_payout,
            CASE
                WHEN sum(p.quantity_sold) = 0::numeric THEN 0::numeric
                ELSE sum(p.delivery_rub) / sum(p.quantity_sold)
            END AS logistics_per_unit,
            CASE
                WHEN sum(p.quantity_sold) = 0::numeric THEN 0::numeric
                ELSE sum(p.margin) / sum(p.quantity_sold)
            END AS margin_per_unit
       FROM supplier_reports_agg_mv p
      WHERE 1 = 1
      GROUP BY p.tenant_id, p.period_month, p.product_name, p.sku
),
with_nm AS (
    -- nmId товара: products.marketplace_sku с безопасным кастом в bigint.
    -- Ручные товары с мусорным marketplace_sku получают NULL → реклама к ним
    -- не присоединится (и join не упадёт).
    SELECT m.*,
           CASE
               WHEN btrim(pr.marketplace_sku) ~ '^[0-9]+$'
                   THEN btrim(pr.marketplace_sku)::bigint
               ELSE NULL::bigint
           END AS nm_id
    FROM margins m
    LEFT JOIN products pr
      ON pr.tenant_id = m.tenant_id
     AND pr.sku::text = m.sku::text
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
    -- Окна для распределения расхода карточки между sku-дублями
    SELECT a.*,
           sum(a.revenue) OVER (
               PARTITION BY a.tenant_id, a.period_month, a.nm_id) AS nm_revenue_total,
           row_number() OVER (
               PARTITION BY a.tenant_id, a.period_month, a.nm_id ORDER BY a.sku) AS rn,
           count(*) OVER (
               PARTITION BY a.tenant_id, a.period_month, a.nm_id) AS sku_count
    FROM with_ad a
),
ad_split AS (
    -- Единственный sku у карточки → весь расход. Несколько sku → пропорционально
    -- выручке, последний (по sku) — остаток копеек. Выручки нет ни у кого
    -- (только возвраты) → поровну, последний — остаток.
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
    CASE
        WHEN d.revenue > 0::numeric
            THEN round(coalesce(d.split_ad_amount, 0::numeric)
                       / d.revenue * 100::numeric, 2)
        ELSE NULL::numeric
    END AS factual_drr_percent,
    d.margin - coalesce(d.split_ad_amount, 0::numeric) AS margin_after_advertising
FROM ad_split d
WITH DATA;

-- Уникальный индекс: обязателен для REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- (tenant_id, period_month, sku) — естественный ключ помесячной агрегации.
CREATE UNIQUE INDEX product_margins_mv_uq
    ON public.product_margins_mv (tenant_id, period_month, sku);

-- Permissions — аналогично существующим view.
ALTER TABLE public.product_margins_mv OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.product_margins_mv TO marketfinance_user;
