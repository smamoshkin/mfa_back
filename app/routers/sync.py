# app/routers/sync.py

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional

from app.database.database import get_db
from app.models.tenant import Tenant
from app.services.sync_service import SyncService
from app.services.sync_orchestrator import sync_orchestrator
from app.routers.auth import get_current_tenant
from app.tasks.sync_tasks import sync_tenant_wb_data
from app.crud import sync_job_crud
from app.schemas.sync_job import (
    SyncJobResponse,
    SyncJobBrief,
    SyncJobListResponse,
    SyncJobStatusResponse,
    SyncLaunchResponse,
)


router = APIRouter(
    prefix="/sync",
    tags=["sync"]
)


# ---------------------------------------------------------------------------
# Существующие эндпоинты запуска — без изменений логики, добавлен orchestrator
# ---------------------------------------------------------------------------

@router.post("/wb/{tenant_id}", response_model=SyncLaunchResponse)
async def sync_wb_data(
    tenant_id: int,
    date_from: date,
    date_to: date,
    current_tenant=Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Ручной запуск синхронизации за указанный период."""
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot sync data for another tenant",
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    if not tenant.wb_api_key:
        raise HTTPException(400, "WB API Key not configured for this tenant")

    job, error = sync_orchestrator.create_and_launch_manual_sync(
        db=db,
        tenant=tenant,
        date_from=date_from,
        date_to=date_to,
    )

    if error and not job:
        raise HTTPException(400, f"Cannot start sync: {error}")

    return SyncLaunchResponse(
        sync_launched=job is not None,
        sync_job_id=job.id if job else None,
        sync_type="manual",
        message=(
            f"Sync started for period {date_from} → {date_to}."
            if job
            else f"Failed to start sync: {error}"
        ),
    )


@router.post("/wb/{tenant_id}/background", response_model=SyncLaunchResponse)
async def sync_wb_data_background(
    tenant_id: int,
    date_from: date,
    date_to: date,
    background_tasks: BackgroundTasks,
    current_tenant=Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Запуск синхронизации в фоновом режиме (алиас для обратной совместимости)."""
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot sync data for another tenant",
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    if not tenant.wb_api_key:
        raise HTTPException(400, "WB API Key not configured for this tenant")

    job, error = sync_orchestrator.create_and_launch_manual_sync(
        db=db,
        tenant=tenant,
        date_from=date_from,
        date_to=date_to,
    )

    return SyncLaunchResponse(
        sync_launched=job is not None,
        sync_job_id=job.id if job else None,
        sync_type="manual",
        message="Sync started as background task." if job else f"Failed: {error}",
    )


@router.get("/task/{task_id}/status")
async def get_task_status(task_id: str):
    """Проверка статуса Celery задачи по task_id."""
    from app.celery_app import celery_app

    try:
        task = celery_app.AsyncResult(task_id)
        return {
            "task_id": task_id,
            "status": task.status,
            "result": task.result if task.ready() else None,
            "info": task.info if hasattr(task, "info") else None,
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to get task status: {str(e)}")


# ---------------------------------------------------------------------------
# Новые эндпоинты истории синхронизаций
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=SyncJobListResponse)
def get_sync_jobs(
    limit: int = 20,
    offset: int = 0,
    current_tenant=Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    История всех запусков синхронизации для текущего tenant.
    Используется для UI экрана истории.
    """
    jobs = sync_job_crud.get_sync_jobs_for_tenant(
        db,
        tenant_id=current_tenant.id,
        limit=limit,
        offset=offset,
    )

    # Для total count делаем отдельный запрос
    from app.models.tenant_sync_job import TenantSyncJob
    total = (
        db.query(TenantSyncJob)
        .filter(TenantSyncJob.tenant_id == current_tenant.id)
        .count()
    )

    return SyncJobListResponse(
        items=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/latest", response_model=SyncJobStatusResponse)
def get_latest_sync_job(
    sync_type: Optional[str] = None,
    current_tenant=Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Последний запуск синхронизации для текущего tenant.
    Опционально фильтровать по sync_type (initial | weekly | manual).

    Используется фронтендом для polling статуса после запуска:
        GET /sync/jobs/latest?sync_type=initial
        — повторять каждые 10 сек пока status != success | failed
    """
    job = sync_job_crud.get_latest_job_for_tenant(
        db,
        tenant_id=current_tenant.id,
        sync_type=sync_type,
    )

    if not job:
        raise HTTPException(
            status_code=404,
            detail="No sync jobs found for this tenant",
        )

    return job


@router.get("/jobs/{job_id}", response_model=SyncJobResponse)
def get_sync_job(
    job_id: int,
    current_tenant=Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Детали конкретного запуска синхронизации.
    Возвращает полные метрики: records, products, api_calls, batches, last_rrdid.
    """
    job = sync_job_crud.get_sync_job(db, job_id=job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")

    # Tenant может видеть только свои jobs
    if job.tenant_id != current_tenant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    return job


@router.get("/status", response_model=SyncJobStatusResponse)
def get_current_sync_status(
    current_tenant=Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Текущий статус синхронизации для tenant.
    Если sync идёт прямо сейчас — вернёт running job.
    Если нет активного — вернёт последний завершённый.

    Удобен для виджета статуса на Dashboard и Profile.
    """
    from app.models.tenant_sync_job import TenantSyncJob
    from sqlalchemy import desc

    # Сначала ищем активный (queued или running)
    active_job = (
        db.query(TenantSyncJob)
        .filter(
            TenantSyncJob.tenant_id == current_tenant.id,
            TenantSyncJob.status.in_(["queued", "running"]),
        )
        .order_by(desc(TenantSyncJob.created_at))
        .first()
    )

    if active_job:
        return active_job

    # Если активного нет — последний завершённый
    last_job = sync_job_crud.get_latest_job_for_tenant(
        db, tenant_id=current_tenant.id
    )

    if not last_job:
        raise HTTPException(
            status_code=404,
            detail="No sync history found for this tenant",
        )

    return last_job