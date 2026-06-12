# app/routers/periodic_sync.py

from fastapi import APIRouter, Depends, HTTPException, status
from celery.result import AsyncResult
from app.tasks.periodic_sync import run_weekly_sync_all_tenants, run_initial_sync_pending_tenants


router = APIRouter(prefix="/periodic-sync", tags=["periodic-sync"])


@router.post("/run-weekly-sync")
async def run_weekly_sync_now():
    """Запустить еженедельную синхронизацию вручную (для тестирования)."""
    try:
        task = run_weekly_sync_all_tenants.delay()
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Weekly sync started for all active tenants",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start weekly sync: {str(e)}",
        )


@router.post("/run-initial-sync-retry")
async def run_initial_sync_retry_now():
    """Запустить проверку зависших initial sync вручную (для тестирования)."""
    try:
        task = run_initial_sync_pending_tenants.delay()
        return {
            "status": "started",
            "task_id": task.id,
            "message": "Initial sync retry check started",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start retry check: {str(e)}",
        )


@router.get("/task-status/{task_id}")
async def get_sync_task_status(task_id: str):
    """Получить статус задачи синхронизации по task_id."""
    task_result = AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": task_result.status,
        "result": task_result.result if task_result.ready() else None,
    }