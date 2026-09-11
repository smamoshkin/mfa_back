from sqlalchemy import Column, Integer, BigInteger, String, Date, Numeric
from .base import Base

class SupplierReportsAggregatedV(Base):
    __tablename__ = 'supplier_reports_aggregated_v'
    
    tenant_id = Column(Integer, primary_key=True)
    period_day = Column(Date)
    period_week = Column(Date)
    period_month = Column(Date)
    period_quarter = Column(Date)
    period_year = Column(Date)
    product_name = Column(String)
    sku = Column(String, primary_key=True)
    quantity_sold = Column(Integer)
    revenue = Column(Numeric(10, 2))
    seller_payout = Column(Numeric(10, 2))
    retail_price_max = Column(Numeric(10, 2))
    storage_fee = Column(Numeric(10, 2))
    regular_deduction = Column(Numeric(10, 2))
    dzhem_deduction = Column(Numeric(10, 2))
    delivery_rub = Column(Numeric(10, 2))
    penalty = Column(Numeric(10, 2))
    acceptance = Column(Numeric(10, 2))
    return_quantity = Column(Integer)
    return_revenue = Column(Numeric(10, 2))

class ProductMarginsMonthV(Base):
    __tablename__ = 'product_margins_month_v'

    tenant_id = Column(Integer, primary_key=True)
    period_month = Column(Date)
    product_name = Column(String)
    sku = Column(String, primary_key=True)
    quantity_sold = Column(Integer)
    revenue = Column(Numeric(10, 2))
    seller_payout = Column(Numeric(10, 2))
    retail_price_max = Column(Numeric(10, 2))
    tax = Column(Numeric(10, 2))
    payout_after_tax = Column(Numeric(10, 2))
    cost_per_unit = Column(Numeric(10, 2))
    total_cost = Column(Numeric(10, 2))
    storage_fee = Column(Numeric(10, 2))
    regular_deduction = Column(Numeric(10, 2))
    dzhem_deduction = Column(Numeric(10, 2))
    delivery_rub = Column(Numeric(10, 2))
    penalty = Column(Numeric(10, 2))
    acceptance = Column(Numeric(10, 2))
    return_quantity = Column(Integer)
    return_revenue = Column(Numeric(10, 2))
    margin = Column(Numeric(10, 2))
    margin_percent_revenue = Column(Numeric(10, 2))
    margin_percent_payout = Column(Numeric(10, 2))
    logistics_per_unit = Column(Numeric(10, 2))
    margin_per_unit = Column(Numeric(10, 2))


# ----------------------------------------------------------------------------
# Материализованные view — на них переключено чтение аналитики (AnalyticsService).
# Логика расчётов та же, что и у обычных view выше (CASE для period_month сохранён),
# см. db/materialized_views/.
#
# В __init__.py и create_all() намеренно НЕ добавляются — по конвенции проекта
# view/мат.view применяются в БД вручную (как tax_rates, product_stock_monthly).
# ----------------------------------------------------------------------------

class SupplierReportsAggMV(Base):
    """Мат.view supplier_reports_agg_mv — подневная агрегация (аналог SupplierReportsAggregatedV)."""
    __tablename__ = 'supplier_reports_agg_mv'

    tenant_id = Column(Integer, primary_key=True)
    period_day = Column(Date, primary_key=True)
    period_week = Column(Date)
    period_month = Column(Date, primary_key=True)
    period_quarter = Column(Date)
    period_year = Column(Date)
    product_name = Column(String)
    sku = Column(String, primary_key=True)
    quantity_sold = Column(Integer)
    revenue = Column(Numeric(10, 2))
    seller_payout = Column(Numeric(10, 2))
    retail_price_max = Column(Numeric(10, 2))
    storage_fee = Column(Numeric(10, 2))
    regular_deduction = Column(Numeric(10, 2))
    dzhem_deduction = Column(Numeric(10, 2))
    delivery_rub = Column(Numeric(10, 2))
    penalty = Column(Numeric(10, 2))
    acceptance = Column(Numeric(10, 2))
    return_quantity = Column(Integer)
    return_revenue = Column(Numeric(10, 2))
    # Колонки ниже есть в мат.view supplier_reports_agg_mv, но отсутствуют
    # в обычной SupplierReportsAggregatedV — они перенесены сюда из DDL,
    # т.к. помесячная product_margins_mv суммирует по ним.
    tax = Column(Numeric(10, 2))
    payout_after_tax = Column(Numeric(10, 2))
    cost_per_unit = Column(Numeric(10, 2))
    total_cost = Column(Numeric(10, 2))
    margin = Column(Numeric(10, 2))


class ProductMarginsMV(Base):
    """Мат.view product_margins_mv — помесячная маржа (аналог ProductMarginsMonthV).

    С 2026-09 дополнена рекламными полями (см. db/materialized_views/05_*.sql):
    nm_id, actual_ad_expense_amount, campaigns_count, advertising_days_count,
    factual_drr_percent (NULL при выручке <= 0), margin_after_advertising.
    Финансовая логика прежних колонок не менялась.
    """
    __tablename__ = 'product_margins_mv'

    tenant_id = Column(Integer, primary_key=True)
    period_month = Column(Date)
    product_name = Column(String)
    sku = Column(String, primary_key=True)
    nm_id = Column(BigInteger)  # nmId WB (products.marketplace_sku), nullable
    quantity_sold = Column(Integer)
    revenue = Column(Numeric(10, 2))
    seller_payout = Column(Numeric(10, 2))
    retail_price_max = Column(Numeric(10, 2))
    tax = Column(Numeric(10, 2))
    payout_after_tax = Column(Numeric(10, 2))
    cost_per_unit = Column(Numeric(10, 2))
    total_cost = Column(Numeric(10, 2))
    storage_fee = Column(Numeric(10, 2))
    regular_deduction = Column(Numeric(10, 2))
    dzhem_deduction = Column(Numeric(10, 2))
    delivery_rub = Column(Numeric(10, 2))
    penalty = Column(Numeric(10, 2))
    acceptance = Column(Numeric(10, 2))
    return_quantity = Column(Integer)
    return_revenue = Column(Numeric(10, 2))
    margin = Column(Numeric(10, 2))
    margin_percent_revenue = Column(Numeric(10, 2))
    margin_percent_payout = Column(Numeric(10, 2))
    logistics_per_unit = Column(Numeric(10, 2))
    margin_per_unit = Column(Numeric(10, 2))
    # --- рекламные поля (фактический расход /adv/v1/upd, аллоцированный на nmId) ---
    actual_ad_expense_amount = Column(Numeric(14, 2))
    campaigns_count = Column(Integer)
    advertising_days_count = Column(Integer)
    factual_drr_percent = Column(Numeric(10, 2))
    margin_after_advertising = Column(Numeric(14, 2))


# ----------------------------------------------------------------------------
# Рекламные материализованные view (db/materialized_views/03_*.sql, 04_*.sql):
# аллокация фактических списаний /adv/v1/upd на nmId пропорционально
# nms[].sum из /adv/v3/fullstats. В create_all() не добавляются — применяются
# вручную (как и остальные view/мат.view проекта).
# ----------------------------------------------------------------------------

class WBAdActualExpenseByNmDayMV(Base):
    """Мат.view mv_wb_ad_actual_expense_by_nm_day — дневная аллокация расходов на nmId."""
    __tablename__ = 'mv_wb_ad_actual_expense_by_nm_day'

    tenant_id = Column(Integer, primary_key=True)
    advert_id = Column(BigInteger, primary_key=True)
    expense_date_msk = Column(Date, primary_key=True)
    expense_month_msk = Column(Date)
    nm_id = Column(BigInteger, primary_key=True)
    currency = Column(String(10), primary_key=True)

    actual_expense_amount = Column(Numeric(14, 2))
    fullstats_nm_spend_amount = Column(Numeric(14, 2))
    fullstats_total_spend_amount = Column(Numeric(14, 2))
    allocation_weight = Column(Numeric(20, 10))
    allocated_actual_expense_amount = Column(Numeric(14, 2))
    reconciliation_delta_amount = Column(Numeric(14, 2))


class WBAdActualExpenseByNmMonthMV(Base):
    """Мат.view mv_wb_ad_actual_expense_by_nm_month — месячные итоги расхода по nmId."""
    __tablename__ = 'mv_wb_ad_actual_expense_by_nm_month'

    tenant_id = Column(Integer, primary_key=True)
    expense_month_msk = Column(Date, primary_key=True)
    nm_id = Column(BigInteger, primary_key=True)
    currency = Column(String(10), primary_key=True)

    allocated_actual_ad_expense_amount = Column(Numeric(14, 2))
    campaigns_count = Column(Integer)
    advertising_days_count = Column(Integer)