# app/models/tenant.py

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
from datetime import datetime

class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)

    # Аутентификация
    login_email = Column(String(255), nullable=False, unique=True, index=True)
    hashed_password = Column(String(255))
    
    # API ключи
    wb_api_key = Column(String(500), nullable=True)
    ozon_api_key = Column(String(500), nullable=True)
    
    # Статусы
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False)
    
    # Таймстампы
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    wb_api_key_expire_at = Column(DateTime(timezone=True), nullable=True)

    # --- Sync state (текущее состояние интеграции) ---
    sync_enabled = Column(Boolean, default=True, nullable=False)
    # True пока не завершён хотя бы один initial sync
    needs_initial_sync = Column(Boolean, default=False, nullable=False)
    # Статус последнего запуска: queued | running | success | failed
    last_sync_status = Column(String(50), nullable=True)
    # Дата последнего УСПЕШНОГО завершения
    last_successful_sync_at = Column(DateTime(timezone=True), nullable=True)
    # Ссылка на последний job (денормализация для быстрого доступа)
    last_sync_run_id = Column(Integer, nullable=True)
    
    # Связи
    products = relationship("Product", back_populates="tenant")
    supplier_reports = relationship("SupplierReport", back_populates="tenant")
    tax_rates = relationship("TaxRate", back_populates="tenant")
    sync_jobs = relationship(
        "TenantSyncJob",
        back_populates="tenant",
        foreign_keys="TenantSyncJob.tenant_id",
        order_by="TenantSyncJob.created_at.desc()",
        cascade="all, delete-orphan",
    )

