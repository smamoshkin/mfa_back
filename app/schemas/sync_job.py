# app/schemas/sync_job.py

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Базовые литералы для валидации
# ---------------------------------------------------------------------------

SYNC_TYPES = {"initial", "weekly", "manual", "retry"}
SYNC_STATUSES = {"queued", "running", "success", "failed", "cancelled"}
TRIGGERED_BY = {"system", "user", "scheduler"}


# ---------------------------------------------------------------------------
# Create — используется внутри CRUD, не экспонируется напрямую в API
# ---------------------------------------------------------------------------

class SyncJobCreate(BaseModel):
    tenant_id: int
    sync_type: str
    triggered_by: str = "system"
    date_from: datetime
    date_to: datetime


# ---------------------------------------------------------------------------
# Response — полный ответ с деталями запуска
# ---------------------------------------------------------------------------

class SyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int

    # Тип и статус
    sync_type: str
    status: str
    triggered_by: str

    # Период
    date_from: datetime
    date_to: datetime

    # Celery
    task_id: Optional[str] = None

    # Тайминги
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Результат
    error_message: Optional[str] = None
    records_imported: Optional[int] = None
    products_synced: Optional[int] = None
    api_calls: Optional[int] = None
    batches_processed: Optional[int] = None
    last_rrdid: Optional[int] = None

    # Вычисляемое поле — длительность в секундах
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


# ---------------------------------------------------------------------------
# Brief — краткий ответ для списков и статус-баров в UI
# ---------------------------------------------------------------------------

class SyncJobBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sync_type: str
    status: str
    triggered_by: str
    date_from: datetime
    date_to: datetime
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    records_imported: Optional[int] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# List — обёртка для пагинированного списка
# ---------------------------------------------------------------------------

class SyncJobListResponse(BaseModel):
    items: list[SyncJobBrief]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Status — минимальный ответ для polling со стороны фронтенда
# ---------------------------------------------------------------------------

class SyncJobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str                          # queued | running | success | failed | cancelled
    sync_type: str
    task_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    records_imported: Optional[int] = None
    error_message: Optional[str] = None

    # Удобный флаг для фронтенда: завершён ли запуск (в любую сторону)
    @property
    def is_finished(self) -> bool:
        return self.status in ("success", "failed", "cancelled")


# ---------------------------------------------------------------------------
# Launch — ответ на запуск sync (из set_wb_key или ручного запуска)
# ---------------------------------------------------------------------------

class SyncLaunchResponse(BaseModel):
    sync_launched: bool
    sync_job_id: Optional[int] = None
    sync_type: Optional[str] = None
    message: str