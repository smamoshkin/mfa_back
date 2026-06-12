from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, DECIMAL, JSON, BigInteger
from sqlalchemy.orm import relationship
from .base import Base
from datetime import datetime

class SupplierReport(Base):
    __tablename__ = "supplier_reports"
    
    id = Column(BigInteger, primary_key=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False)
    
    # Обязательные поля для отчетности
    realizationreport_id = Column(BigInteger, nullable=True)
    rrd_id = Column(BigInteger, nullable=True) # Уникальный идентификатор строки на стороне площадки
    date_from = Column(Date, nullable=False) # Дата начала периода поставки данных
    date_to = Column(Date, nullable=False) # Дата окончания периода поставки данных
    sale_dt = Column(Date, nullable=False) # Дата продажи товара
    # order_id = Column(String(255), nullable=False)
    sku = Column(String(100), nullable=False)           # Артикул продавца (WB: sa_name)
    doc_type_name = Column(String(1000), nullable=False) # Тип строки
    supplier_oper_name = Column(String(1000), nullable=False) # Тип операции
    quantity = Column(Integer, default=0) # Количество проданых товаров
    retail_amount = Column(DECIMAL(10, 2))               # Цена продажи
    amount_for_pay = Column(DECIMAL(10, 2))               # Сумма к перечислению продавцу
    retail_price = Column(DECIMAL(10, 2))               # Розничная цена
    storage_fee = Column(DECIMAL(10, 2))               # Хранение
    bonus_type_name = Column(String(100), nullable=False)           # Наименование типа бонуса
    deduction = Column(DECIMAL(10, 2))               # Удержание
    delivery_rub = Column(DECIMAL(10, 2))               # Услуги по доставке
    penalty = Column(DECIMAL(10, 2))               # Штрафы
    acceptance = Column(DECIMAL(10, 2))               # Платная приемка
    
    # Гибкая часть
    raw_data = Column(JSON)  # Все оригинальные данные из отчета
    extracted_fields = Column(JSON)  # Часто используемые поля
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    tenant = relationship("Tenant", back_populates="supplier_reports")