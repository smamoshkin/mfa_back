from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

class AnalyticsFilters(BaseModel):
    date_from: date = Field(..., description="Дата начала периода")
    date_to: date = Field(..., description="Дата окончания периода")
    group_by: str = Field("month", description="Группировка (day, week, month, year)")
    sku: Optional[str] = Field(None, description="Фильтр по SKU")
    min_margin_percent: Optional[float] = Field(None, ge=0, le=100, description="Минимальная рентабельность %")
    min_quantity: Optional[int] = Field(None, ge=0, description="Минимальное количество продаж")
    
    class Config:
        json_schema_extra = {
            "example": {
                "date_from": "2024-01-01",
                "date_to": "2024-01-31",
                "group_by": "month",
                "sku": "ABC123",
                "min_margin_percent": 10.5,
                "min_quantity": 5
            }
        }