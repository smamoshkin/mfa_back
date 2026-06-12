# schemas/tax_rate.py
from pydantic import BaseModel, ConfigDict, Field
from datetime import date, datetime
from typing import Optional
from decimal import Decimal

class TaxRateBase(BaseModel):
    tax_rate: Decimal = Field(
        ..., 
        ge=0, 
        le=100, 
        description="Налоговая ставка в процентах (0-100)"
    )
    start_date: date = Field(..., description="Дата начала действия")
    end_date: Optional[date] = Field(None, description="Дата окончания (если не указана - действует бессрочно)")
    created_by: Optional[str] = Field(None, description="Кто внес изменение")

class TaxRateCreate(TaxRateBase):
    # tenant_id берется из текущего пользователя
    pass

class TaxRateUpdate(BaseModel):
    tax_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_by: Optional[str] = None

class TaxRate(TaxRateBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    tenant_id: int
    created_at: datetime

class TaxRateCurrent(BaseModel):
    """Текущая активная ставка налога"""
    tax_rate: Decimal
    start_date: date
    end_date: Optional[date] = None
    is_current: bool = True