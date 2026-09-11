# models/wb_advertising.py
from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, Numeric, ForeignKey, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from .base import Base


class WBAdExpenseOperation(Base):
    """
    Сырые фактические списания WB из GET /adv/v1/upd.

    Одна строка — одна операция списания. Идемпотентность по
    (tenant_id, source_hash): sha256 канонического JSON записи WB.
    updNum — НЕ идентификатор (повторяется, бывает 0).

    День/месяц расхода (Europe/Moscow) посчитаны при записи и хранятся
    отдельными колонками — агрегации не зависят от таймзоны сессии.

    Таблица применяется вручную DDL-скриптом db/tables/wb_ad_expense_operations.sql
    (конвенция проекта: в create_all() в main.py НЕ добавляется, как tax_rates
    и product_stock_monthly).
    """
    __tablename__ = "wb_ad_expense_operations"

    id = Column(BigInteger, primary_key=True)                       # bigserial (в DDL)
    tenant_id = Column(Integer, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    advert_id = Column(BigInteger, nullable=False)                  # advertId кампании

    expense_datetime = Column(DateTime(timezone=True), nullable=False)  # updTime как есть
    expense_date_msk = Column(Date, nullable=False)                 # дата updTime в Europe/Moscow
    expense_month_msk = Column(Date, nullable=False)                # первое число месяца expense_date_msk

    expense_amount = Column(Numeric(14, 2), nullable=False)          # updSum, Decimal
    currency = Column(String(10), nullable=False, default='RUB', server_default='RUB')

    wb_upd_num = Column(BigInteger, nullable=True)                  # updNum (не уникален)
    campaign_name = Column(String(500), nullable=True)              # campName
    payment_type = Column(String(100), nullable=True)               # paymentType
    advert_type = Column(Integer, nullable=True)                    # advertType
    advert_status = Column(Integer, nullable=True)                  # advertStatus

    source_hash = Column(String(64), nullable=False)                # sha256 канонического JSON записи
    raw_payload = Column(JSONB, nullable=False)                     # исходная запись WB целиком

    synced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'source_hash', name='uq_wb_ad_expense_ops_tenant_hash'),
        CheckConstraint('expense_amount >= 0', name='ck_wb_ad_expense_ops_amount_nonneg'),
        Index('ix_wb_ad_expense_ops_tenant_date', 'tenant_id', 'expense_date_msk'),
        Index('ix_wb_ad_expense_ops_tenant_month', 'tenant_id', 'expense_month_msk'),
        Index('ix_wb_ad_expense_ops_tenant_advert_date', 'tenant_id', 'advert_id', 'expense_date_msk'),
    )


class WBAdProductDailyStat(Base):
    """
    Дневная детализация рекламной статистики по товару из
    GET /adv/v3/fullstats.

    Зерно: (tenant_id, advert_id, stat_date_msk, app_type, nm_id).
    Один nmId в нескольких appType — отдельные строки; при агрегации по
    артикулу суммируются (это делает MV аллокации).

    Единственный товарный расход — nms[].sum (stat_spend_amount).
    days[].sum и apps[].sum сюда НЕ пишутся (двойной учёт).
    attributed_orders_amount = nms[].sum_price — справочно, в аллокации
    фактических списаний не участвует.

    Повторная загрузка fullstats — upsert по natural key (WB уточняет
    статистику прошедших дней).

    Таблица применяется вручную DDL-скриптом db/tables/wb_ad_product_daily_stats.sql.
    """
    __tablename__ = "wb_ad_product_daily_stats"

    id = Column(BigInteger, primary_key=True)                       # bigserial (в DDL)
    tenant_id = Column(Integer, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    advert_id = Column(BigInteger, nullable=False)

    stat_date_msk = Column(Date, nullable=False)                    # days[].date в Europe/Moscow
    stat_month_msk = Column(Date, nullable=False)                   # первое число месяца stat_date_msk

    app_type = Column(Integer, nullable=False)                      # apps[].appType
    nm_id = Column(BigInteger, nullable=False)                      # nms[].nmId
    product_name = Column(String(1000), nullable=True)              # nms[].name

    views = Column(BigInteger, nullable=False, default=0)
    clicks = Column(BigInteger, nullable=False, default=0)
    atbs = Column(BigInteger, nullable=False, default=0)            # добавления в корзину
    orders = Column(BigInteger, nullable=False, default=0)
    shks = Column(BigInteger, nullable=False, default=0)
    canceled = Column(BigInteger, nullable=False, default=0)

    stat_spend_amount = Column(Numeric(14, 2), nullable=False, default=0)        # ТОЛЬКО nms[].sum
    attributed_orders_amount = Column(Numeric(14, 2), nullable=False, default=0) # nms[].sum_price

    cpc = Column(Numeric(14, 4), nullable=True)
    ctr = Column(Numeric(14, 4), nullable=True)
    cr = Column(Numeric(14, 4), nullable=True)

    currency = Column(String(10), nullable=False, default='RUB', server_default='RUB')

    raw_payload = Column(JSONB, nullable=True)                      # исходная товарная строка nms[]

    synced_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'advert_id', 'stat_date_msk', 'app_type', 'nm_id',
                         name='uq_wb_ad_product_daily_stats_natural_key'),
        CheckConstraint('stat_spend_amount >= 0', name='ck_wb_ad_product_daily_stats_spend_nonneg'),
        CheckConstraint('attributed_orders_amount >= 0', name='ck_wb_ad_product_daily_stats_attributed_nonneg'),
        Index('ix_wb_ad_product_daily_stats_tenant_advert_date', 'tenant_id', 'advert_id', 'stat_date_msk'),
        Index('ix_wb_ad_product_daily_stats_tenant_nm_date', 'tenant_id', 'nm_id', 'stat_date_msk'),
        Index('ix_wb_ad_product_daily_stats_tenant_month_nm', 'tenant_id', 'stat_month_msk', 'nm_id'),
    )
