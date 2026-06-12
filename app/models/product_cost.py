from sqlalchemy import Column, Integer, DateTime, Date, ForeignKey, DECIMAL, String
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base
from datetime import datetime

class ProductCost(Base):
    __tablename__ = "product_costs"
    
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    cost = Column(DECIMAL(10, 2), nullable=False)  # Себестоимость
    start_date = Column(Date, nullable=False)      # Дата начала действия цены
    end_date = Column(Date)                        # Дата окончания (если нужно)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String(100))               # Кто внес изменение
    
    # Связи
    product = relationship("Product", back_populates="cost_records")