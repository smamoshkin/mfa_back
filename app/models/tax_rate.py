# models/tax_rate.py
from sqlalchemy import Column, Integer, DateTime, Date, ForeignKey, DECIMAL, String
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .base import Base
from datetime import datetime

class TaxRate(Base):
    __tablename__ = "tax_rates"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    tax_rate = Column(DECIMAL(5, 2), nullable=False)  # Ставка в процентах (0-100)
    start_date = Column(Date, nullable=False)          # Дата начала действия ставки
    end_date = Column(Date)                            # Дата окончания (NULL = действует бессрочно)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String(100))                   # Кто внес изменение
    
    # Связи
    tenant = relationship("Tenant", back_populates="tax_rates")