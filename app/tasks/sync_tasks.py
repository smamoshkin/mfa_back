# app/tasks/sync_tasks.py

import asyncio
import logging
from datetime import date, datetime

from app.celery_app import celery_app
from app.database.database import SessionLocal
from app.models.tenant import Tenant
from app.services.sync_service import SyncService

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name='sync_tenant_wb_data')
def sync_tenant_wb_data(
    self,
    tenant_id: int,
    date_from: str,
    date_to: str,
    sync_type: str = "manual",   # initial | weekly | manual | retry
    job_id: int = None,          # ID записи в tenant_sync_jobs
):
    """
    Универсальная Celery задача для синхронизации данных WB за любой период.

    Вызывается через:
    - SyncOrchestrator.create_and_launch_initial_sync()
    - SyncOrchestrator.create_and_launch_weekly_sync()
    - SyncOrchestrator.create_and_launch_manual_sync()
    - Напрямую через sync_tenant_wb_data.delay(...) для обратной совместимости
    """
    # Импорт здесь, чтобы избежать циклических зависимостей
    # (orchestrator импортирует sync_tasks, sync_tasks импортирует orchestrator)
    from app.services.sync_orchestrator import sync_orchestrator

    db = SessionLocal()

    try:
        logger.info(
            f"🚀 Celery task '{self.request.id}' started | "
            f"tenant={tenant_id} | type={sync_type} | "
            f"period={date_from} → {date_to} | job_id={job_id}"
        )

        # --- Статус: стартуем ---
        self.update_state(
            state='PROGRESS',
            meta={
                'tenant_id': tenant_id,
                'sync_type': sync_type,
                'job_id': job_id,
                'status': 'Starting...',
                'progress': 0,
            }
        )

        # --- Уведомляем orchestrator: задача запущена ---
        if job_id:
            sync_orchestrator.on_sync_started(db, job_id, self.request.id)

        # --- Загружаем tenant ---
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            error_msg = f"Tenant {tenant_id} not found"
            logger.error(error_msg)
            _handle_failure(self, db, sync_orchestrator, job_id, error_msg, tenant_id)
            return _error_result(self, tenant_id, error_msg)

        if not tenant.wb_api_key:
            error_msg = f"WB API key not configured for tenant {tenant_id}"
            logger.error(error_msg)
            _handle_failure(self, db, sync_orchestrator, job_id, error_msg, tenant_id)
            return _error_result(self, tenant_id, error_msg)

        # --- Статус: загрузка данных ---
        self.update_state(
            state='PROGRESS',
            meta={
                'tenant_id': tenant_id,
                'sync_type': sync_type,
                'job_id': job_id,
                'status': 'Loading data from WB API...',
                'progress': 10,
            }
        )

        # --- Запускаем синхронизацию ---
        sync_service = SyncService()

        metrics = asyncio.run(
            sync_service.sync_wb_data_for_period(
                db=db,
                tenant=tenant,
                date_from=date.fromisoformat(date_from),
                date_to=date.fromisoformat(date_to),
            )
        )

        # --- Уведомляем orchestrator: успех ---
        if job_id:
            sync_orchestrator.on_sync_success(db, job_id, metrics)

        logger.info(
            f"✅ Celery task '{self.request.id}' completed | "
            f"tenant={tenant_id} | type={sync_type} | "
            f"records={metrics.get('total_records')} | "
            f"products={metrics.get('products_synced')}"
        )

        result = {
            'status': 'success',
            'task_id': self.request.id,
            'tenant_id': tenant_id,
            'sync_type': sync_type,
            'job_id': job_id,
            'period': f"{date_from} → {date_to}",
            'metrics': metrics,
            'completed_at': datetime.utcnow().isoformat(),
        }

        self.update_state(state='SUCCESS', meta=result)
        return result

    except Exception as e:
        error_msg = f"Sync failed for tenant {tenant_id}: {str(e)}"
        logger.error(f"❌ {error_msg}", exc_info=True)

        _handle_failure(self, db, sync_orchestrator, job_id, error_msg, tenant_id)

        return _error_result(self, tenant_id, str(e), sync_type, job_id)

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _handle_failure(self, db, orchestrator, job_id, error_msg, tenant_id):
    """Обновляет статус job и tenant при ошибке."""
    if job_id:
        try:
            orchestrator.on_sync_failed(db, job_id, error_msg)
        except Exception as ex:
            logger.error(
                f"Failed to update sync job {job_id} on failure: {ex}"
            )


def _error_result(self, tenant_id, error, sync_type="manual", job_id=None):
    """Стандартный словарь результата при ошибке."""
    return {
        'status': 'error',
        'task_id': self.request.id,
        'tenant_id': tenant_id,
        'sync_type': sync_type,
        'job_id': job_id,
        'error': error,
        'failed_at': datetime.utcnow().isoformat(),
    }