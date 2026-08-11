# models/product_stock.py
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.schema import UniqueConstraint
from .base import Base

class ProductStockMonthly(Base):
    __tablename__ = "product_stock_monthly"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    sku = Column(String(100), nullable=False)            # Артикул продавца
    nm_id = Column(String(100), nullable=False)          # nmId WB (для трассируемости)
    period_month = Column(Date, nullable=False)          # Первое число месяца, к которому относится снапшот
    quantity = Column(Integer, nullable=False, default=0)  # Остаток на складах WB, сумма по всем складам
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'sku', 'period_month', name='uix_tenant_sku_period'),
    )
