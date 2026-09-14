# models/analytics_tables.py
"""
Обычные таблицы агрегатов аналитики (TODO №1 — переход с мат.view на таблицы).

Заполняются кодом приложения (app/services/aggregates_service.py):
recompute_supplier_agg() и recompute_product_margins() — DELETE затронутых
месяцев + INSERT...SELECT. Триггеры: полный синк, импорт/правка себестоимостей,
изменение налоговых ставок, рекламная загрузка.

⚠️ info={'skip_create_all': True} — create_all() в main.py эти таблицы НЕ
создаёт: схема применяется владельцем вручную DDL-скриптами
db/tables/supplier_reports_agg.sql и db/tables/product_margins.sql
(контроль изменений схемы — осознанное решение владельца).
"""
from sqlalchemy import Column, Integer, BigInteger, String, Date, Numeric, PrimaryKeyConstraint, Index
from .base import Base


class SupplierReportsAgg(Base):
    """Подневная агрегация продаж (замена supplier_reports_agg_mv).

    Зерно: (tenant_id, period_day, period_month, sku). period_month входит
    в ключ: считается через CASE (корректировка с sale_dt вне окна отчёта
    прицепляется к месяцу date_to), поэтому один (tenant, day, sku) может
    легально существовать в двух месяцах.
    """
    __tablename__ = "supplier_reports_agg"

    tenant_id = Column(Integer, primary_key=True)
    period_day = Column(Date, primary_key=True)
    period_month = Column(Date, primary_key=True)
    product_name = Column(String)
    sku = Column(String(100), primary_key=True)

    quantity_sold = Column(Integer)
    revenue = Column(Numeric)
    seller_payout = Column(Numeric)
    retail_price_max = Column(Numeric)
    storage_fee = Column(Numeric)
    regular_deduction = Column(Numeric)
    dzhem_deduction = Column(Numeric)
    delivery_rub = Column(Numeric)
    penalty = Column(Numeric)
    acceptance = Column(Numeric)
    return_quantity = Column(Integer)
    return_revenue = Column(Numeric)

    tax = Column(Numeric)
    payout_after_tax = Column(Numeric)
    cost_per_unit = Column(Numeric)
    total_cost = Column(Numeric)
    margin = Column(Numeric)

    __table_args__ = (
        PrimaryKeyConstraint('tenant_id', 'period_day', 'period_month', 'sku',
                             name='supplier_reports_agg_pkey'),
        Index('ix_supplier_reports_agg_tenant_month', 'tenant_id', 'period_month'),
        Index('ix_supplier_reports_agg_tenant_day', 'tenant_id', 'period_day'),
        {'info': {'skip_create_all': True}},
    )


class ProductMargins(Base):
    """Помесячная рентабельность по артикулам (замена product_margins_mv).

    Зерно: (tenant_id, period_month, sku). nm_id — карточка WB
    (products.marketplace_sku); рекламные поля — фактические списания,
    аллоцированные на карточку (при sku-дублях — пропорционально выручке).
    factual_drr_percent = NULL при выручке <= 0.
    """
    __tablename__ = "product_margins"

    tenant_id = Column(Integer, primary_key=True)
    period_month = Column(Date, primary_key=True)
    product_name = Column(String)
    sku = Column(String(100), primary_key=True)
    nm_id = Column(BigInteger)

    quantity_sold = Column(Integer)
    revenue = Column(Numeric)
    seller_payout = Column(Numeric)
    retail_price_max = Column(Numeric)
    tax = Column(Numeric)
    payout_after_tax = Column(Numeric)
    cost_per_unit = Column(Numeric)
    total_cost = Column(Numeric)
    storage_fee = Column(Numeric)
    regular_deduction = Column(Numeric)
    dzhem_deduction = Column(Numeric)
    delivery_rub = Column(Numeric)
    penalty = Column(Numeric)
    acceptance = Column(Numeric)
    return_quantity = Column(Integer)
    return_revenue = Column(Numeric)
    margin = Column(Numeric)
    margin_percent_revenue = Column(Numeric)
    margin_percent_payout = Column(Numeric)
    logistics_per_unit = Column(Numeric)
    margin_per_unit = Column(Numeric)

    actual_ad_expense_amount = Column(Numeric(14, 2))
    campaigns_count = Column(Integer)
    advertising_days_count = Column(Integer)
    factual_drr_percent = Column(Numeric)
    margin_after_advertising = Column(Numeric)

    __table_args__ = (
        PrimaryKeyConstraint('tenant_id', 'period_month', 'sku', name='product_margins_pkey'),
        Index('ix_product_margins_tenant_nm_month', 'tenant_id', 'nm_id', 'period_month'),
        {'info': {'skip_create_all': True}},
    )
