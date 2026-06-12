from fastapi import APIRouter, Depends, HTTPException, status  # 👈 ДОБАВЛЯЕМ
from app.tasks.sync_tasks import sync_tenant_wb_data
from datetime import date
from app.routers.auth import get_current_tenant  # 👈 ДОБАВЛЯЕМ

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"]
)

@router.post("/sync/wb/{tenant_id}")
def start_sync_task(
    tenant_id: int,
    date_from: date,
    date_to: date,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
):
    """
    Запуск фоновой задачи синхронизации WB за любой период
    """
    # Проверяем права доступа
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot start sync for another tenant"
        )
    
    task = sync_tenant_wb_data.delay(
        tenant_id=tenant_id,
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat()
    )
    
    return {
        "status": "started",
        "task_id": task.id,
        "tenant_id": tenant_id,
        "period": f"{date_from} to {date_to}"
    }

@router.get("/status/{task_id}")
def get_task_status(
    task_id: str,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА (опционально, но лучше добавить)
):
    """Проверка статуса задачи"""
    task = sync_tenant_wb_data.AsyncResult(task_id)
    
    # Дополнительная проверка: убедиться, что задача принадлежит текущему tenant
    if task.ready() and task.result:
        result = task.result
        if 'tenant_id' in result and result['tenant_id'] != current_tenant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )
    
    return {
        "task_id": task_id,
        "status": task.status,
        "result": task.result if task.ready() else None
    }