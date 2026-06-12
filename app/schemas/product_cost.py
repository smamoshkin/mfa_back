from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from typing import Optional
from decimal import Decimal

class ProductCostBase(BaseModel):
    cost: Decimal
    start_date: date
    end_date: Optional[date] = None
    created_by: Optional[str] = None

class ProductCostCreate(ProductCostBase):
    product_id: int

class ProductCostUpdate(BaseModel):
    cost: Optional[Decimal] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_by: Optional[str] = None

class ProductCost(ProductCostBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    product_id: int
    created_at: datetime