# app/models/tenant_sync_job.py

from sqlalchemy import (
    Column, Integer, BigInteger, String, DateTime,
    Text, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base


class TenantSyncJob(Base):
    __tablename__ = "tenant_sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Тип и статус ---
    # sync_type: initial | weekly | manual | retry
    sync_type = Column(String(20), nullable=False)
    # status: queued | running | success | failed | cancelled
    status = Column(String(20), nullable=False, default="queued")
    # triggered_by: system | user | scheduler
    triggered_by = Column(String(20), nullable=False, default="system")

    # --- Период загрузки ---
    date_from = Column(DateTime(timezone=True), nullable=False)
    date_to = Column(DateTime(timezone=True), nullable=False)

    # --- Celery ---
    task_id = Column(String(255), nullable=True, index=True)

    # --- Тайминги ---
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # --- Результат и метрики ---
    error_message = Column(Text, nullable=True)
    records_imported = Column(Integer, nullable=True)
    products_synced = Column(Integer, nullable=True)
    api_calls = Column(Integer, nullable=True)
    batches_processed = Column(Integer, nullable=True)
    # Последний rrdid для возможности resume при ошибке
    last_rrdid = Column(BigInteger, nullable=True)

    # --- Связь ---
    tenant = relationship(
        "Tenant",
        back_populates="sync_jobs",
        foreign_keys=[tenant_id],
    )

    # --- Индексы ---
    __table_args__ = (
        # Быстрый поиск активных задач по tenant
        Index("ix_sync_jobs_tenant_status", "tenant_id", "status"),
        # Быстрый поиск по типу для проверки наличия initial sync
        Index("ix_sync_jobs_tenant_type", "tenant_id", "sync_type"),
    )