# schemas/wb_advertising.py
from pydantic import BaseModel, ConfigDict, Field
from datetime import date, datetime
from typing import Optional, Any
from decimal import Decimal


# ----------------------------------------------------------------------------
# Чтение из БД
# ----------------------------------------------------------------------------

class WBAdExpenseOperationRead(BaseModel):
    """Запись фактического списания /adv/v1/upd."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    advert_id: int

    expense_datetime: datetime
    expense_date_msk: date
    expense_month_msk: date

    expense_amount: Decimal
    currency: str

    wb_upd_num: Optional[int] = None
    campaign_name: Optional[str] = None
    payment_type: Optional[str] = None
    advert_type: Optional[int] = None
    advert_status: Optional[int] = None

    source_hash: str
    raw_payload: Optional[dict[str, Any]] = None

    synced_at: datetime
    created_at: datetime
    updated_at: datetime


class WBAdProductDailyStatRead(BaseModel):
    """Дневная товарная строка /adv/v3/fullstats."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    advert_id: int

    stat_date_msk: date
    stat_month_msk: date

    app_type: int
    nm_id: int
    product_name: Optional[str] = None

    views: int
    clicks: int
    atbs: int
    orders: int
    shks: int
    canceled: int

    stat_spend_amount: Decimal
    attributed_orders_amount: Decimal

    cpc: Optional[Decimal] = None
    ctr: Optional[Decimal] = None
    cr: Optional[Decimal] = None

    currency: str
    raw_payload: Optional[dict[str, Any]] = None

    synced_at: datetime
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------------
# Приём payload (форма записи WB)
# ----------------------------------------------------------------------------

class WBAdExpenseOperationIngest(BaseModel):
    """Одна запись из ответа GET /adv/v1/upd (как отдаёт WB).

    Пример:
        {"updTime": "2026-09-05T16:15:00.019395+03:00", "campName": "...",
         "paymentType": "Баланс", "updNum": 313782565, "updSum": 1000,
         "advertId": 26451117, "advertType": 9, "advertStatus": 9,
         "currency": "RUB"}
    """
    updTime: datetime = Field(..., description="Момент списания; день/месяц расхода — в Europe/Moscow")
    advertId: int = Field(..., description="Идентификатор кампании")
    updSum: Decimal = Field(..., ge=0, description="Фактически списанная сумма")
    currency: str = Field('RUB', max_length=10)

    campName: Optional[str] = None
    paymentType: Optional[str] = None
    updNum: Optional[int] = None          # не идентификатор: повторяется, бывает 0
    advertType: Optional[int] = None
    advertStatus: Optional[int] = None


class WBAdProductDailyStatIngest(BaseModel):
    """Нормализованная товарная строка из /adv/v3/fullstats (после развёртки
    campaigns → days → apps → nms; день приведён к Europe/Moscow)."""
    advert_id: int
    stat_date_msk: date
    stat_month_msk: date
    app_type: int
    nm_id: int

    product_name: Optional[str] = None

    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    shks: int = 0
    canceled: int = 0

    stat_spend_amount: Decimal = Field(0, ge=0, description="Только nms[].sum")
    attributed_orders_amount: Decimal = Field(0, ge=0, description="nms[].sum_price")

    cpc: Optional[Decimal] = None
    ctr: Optional[Decimal] = None
    cr: Optional[Decimal] = None

    currency: str = Field('RUB', max_length=10)
    raw_payload: Optional[dict[str, Any]] = None


# ----------------------------------------------------------------------------
# Итоги из месячной MV
# ----------------------------------------------------------------------------

class WBAdSpendByNmMonth(BaseModel):
    """Фактический рекламный расход по артикулу за месяц
    (mv_wb_ad_actual_expense_by_nm_month)."""
    model_config = ConfigDict(from_attributes=True)

    tenant_id: int
    expense_month_msk: date
    nm_id: int
    currency: str

    allocated_actual_ad_expense_amount: Decimal
    campaigns_count: int
    advertising_days_count: int
