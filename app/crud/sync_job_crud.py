# app/crud/sync_job_crud.py

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.tenant_sync_job import TenantSyncJob
from app.models.tenant import Tenant


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

def create_sync_job(
    db: Session,
    tenant_id: int,
    sync_type: str,
    date_from: datetime,
    date_to: datetime,
    triggered_by: str = "system",
) -> TenantSyncJob:
    """
    Создаёт новую запись запуска синхронизации со статусом 'queued'.
    sync_type: initial | weekly | manual | retry
    triggered_by: system | user | scheduler
    """
    job = TenantSyncJob(
        tenant_id=tenant_id,
        sync_type=sync_type,
        status="queued",
        triggered_by=triggered_by,
        date_from=date_from,
        date_to=date_to,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# READ
# ---------------------------------------------------------------------------

def get_sync_job(db: Session, job_id: int) -> Optional[TenantSyncJob]:
    """Получить job по ID."""
    return db.query(TenantSyncJob).filter(TenantSyncJob.id == job_id).first()


def get_sync_job_by_task_id(db: Session, task_id: str) -> Optional[TenantSyncJob]:
    """Получить job по Celery task_id."""
    return db.query(TenantSyncJob).filter(TenantSyncJob.task_id == task_id).first()


def get_latest_job_for_tenant(
    db: Session,
    tenant_id: int,
    sync_type: Optional[str] = None,
) -> Optional[TenantSyncJob]:
    """
    Последний job для tenant.
    Опционально фильтровать по sync_type (например, 'initial').
    """
    query = db.query(TenantSyncJob).filter(TenantSyncJob.tenant_id == tenant_id)
    if sync_type:
        query = query.filter(TenantSyncJob.sync_type == sync_type)
    return query.order_by(desc(TenantSyncJob.created_at)).first()


def get_sync_jobs_for_tenant(
    db: Session,
    tenant_id: int,
    limit: int = 20,
    offset: int = 0,
) -> list[TenantSyncJob]:
    """История запусков для tenant (новые сначала)."""
    return (
        db.query(TenantSyncJob)
        .filter(TenantSyncJob.tenant_id == tenant_id)
        .order_by(desc(TenantSyncJob.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_completed_initial_sync(db: Session, tenant_id: int) -> Optional[TenantSyncJob]:
    """
    Возвращает завершённый initial sync, если он есть.
    Используется для проверки: нужно ли запускать initial sync.
    """
    return (
        db.query(TenantSyncJob)
        .filter(
            TenantSyncJob.tenant_id == tenant_id,
            TenantSyncJob.sync_type == "initial",
            TenantSyncJob.status == "success",
        )
        .first()
    )


# ---------------------------------------------------------------------------
# STATUS CHECKS
# ---------------------------------------------------------------------------

def is_sync_running(db: Session, tenant_id: int) -> bool:
    """
    Проверяет, есть ли активный (queued или running) sync для tenant.
    Защита от параллельных запусков.
    """
    active_job = (
        db.query(TenantSyncJob)
        .filter(
            TenantSyncJob.tenant_id == tenant_id,
            TenantSyncJob.status.in_(["queued", "running"]),
        )
        .first()
    )
    return active_job is not None


def has_completed_initial_sync(db: Session, tenant_id: int) -> bool:
    """True если initial sync успешно завершён хотя бы раз."""
    return get_completed_initial_sync(db, tenant_id) is not None


# ---------------------------------------------------------------------------
# UPDATE — смена статусов
# ---------------------------------------------------------------------------

def mark_job_running(
    db: Session,
    job_id: int,
    task_id: str,
) -> Optional[TenantSyncJob]:
    """
    Вызывается в начале Celery task.
    Устанавливает статус 'running', сохраняет task_id и started_at.
    """
    job = get_sync_job(db, job_id)
    if not job:
        return None

    job.status = "running"
    job.task_id = task_id
    job.started_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)
    return job


def mark_job_success(
    db: Session,
    job_id: int,
    metrics: dict,
) -> Optional[TenantSyncJob]:
    """
    Вызывается после успешного завершения Celery task.
    Сохраняет статус, финальные метрики и finished_at.

    Ожидаемые ключи в metrics (все опциональны):
        total_records, products_synced, api_calls,
        batches_processed, last_rrdid
    """
    job = get_sync_job(db, job_id)
    if not job:
        return None

    job.status = "success"
    job.finished_at = datetime.now(timezone.utc)
    job.error_message = None

    # Метрики из SyncService
    job.records_imported  = metrics.get("total_records")
    job.products_synced   = metrics.get("products_synced")
    job.api_calls         = metrics.get("api_calls")
    job.batches_processed = metrics.get("batches_processed")
    job.last_rrdid        = metrics.get("last_rrdid")

    db.commit()
    db.refresh(job)
    return job


def mark_job_failed(
    db: Session,
    job_id: int,
    error: str,
) -> Optional[TenantSyncJob]:
    """
    Вызывается при ошибке в Celery task.
    """
    job = get_sync_job(db, job_id)
    if not job:
        return None

    job.status = "failed"
    job.finished_at = datetime.now(timezone.utc)
    job.error_message = error

    db.commit()
    db.refresh(job)
    return job


def mark_job_cancelled(db: Session, job_id: int) -> Optional[TenantSyncJob]:
    """Отмена job (например, при повторном сохранении токена пока идёт sync)."""
    job = get_sync_job(db, job_id)
    if not job:
        return None

    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# UPDATE — обновление tenant после смены статуса job
# ---------------------------------------------------------------------------

def update_tenant_sync_state(
    db: Session,
    tenant_id: int,
    job: TenantSyncJob,
) -> None:
    """
    Денормализует текущее состояние sync в таблицу tenant.
    Вызывается после mark_job_success / mark_job_failed.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        return

    tenant.last_sync_status = job.status
    tenant.last_sync_run_id = job.id

    if job.status == "success":
        tenant.last_successful_sync_at = job.finished_at
        # Снимаем флаг первичной загрузки после успешного initial sync
        if job.sync_type == "initial":
            tenant.needs_initial_sync = False

    if job.status == "running":
        tenant.last_sync_status = "running"

    db.commit()