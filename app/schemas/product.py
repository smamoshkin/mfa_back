from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional, List
from decimal import Decimal

class ProductBase(BaseModel):
    sku: str
    marketplace_sku: str  # 👈 Новое поле
    foto: Optional[str] = None  # 👈 Новое поле
    barcode: Optional[str] = None  # 👈 Новое поле
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True

class ProductCreate(ProductBase):
    tenant_id: int # tenant_id НЕ ДОЛЖЕН быть здесь - он берется из токена
    sku: str
    marketplace_sku: str
    name: str = ""
    category: Optional[str] = None
    barcode: Optional[str] = None
    is_active: bool = True

class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    marketplace_sku: Optional[str] = None  # 👈 Новое поле
    foto: Optional[str] = None  # 👈 Новое поле
    barcode: Optional[str] = None  # 👈 Новое поле
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None

class Product(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    tenant_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

class ProductEnrichRequest(BaseModel):
    skus: List[str]
    force_update: bool = False