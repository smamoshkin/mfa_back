from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.schema import UniqueConstraint
from .base import Base
from datetime import datetime

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    sku = Column(String(100), nullable=False)  # Артикул продавца
    marketplace_sku = Column(String(100), nullable=False)  # Артикул площадки
    foto = Column(String(100), nullable=True)  # Фото товара
    barcode = Column(String(100))              # Штрихкод
    name = Column(String(500))                 # Наименование товара
    description = Column(Text, nullable=True)  # Описание товара
    is_active = Column(Boolean, default=True)  # Флаг активности товара
    category = Column(String(255))             # Категория
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Связи
    tenant = relationship("Tenant", back_populates="products")
    cost_records = relationship("ProductCost", back_populates="product")
    
    __table_args__ = (
        UniqueConstraint('tenant_id', 'sku', name='uix_tenant_sku'),
    )