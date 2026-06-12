from app.celery_app import celery_app
from app.services.sync_service import SyncService
from app.database.database import SessionLocal
from app.models.tenant import Tenant
from datetime import date, datetime
import asyncio
import logging

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name='sync_tenant_wb_data')
def sync_tenant_wb_data(self, tenant_id: int, date_from: str, date_to: str):
    """
    УНИВЕРСАЛЬНАЯ Celery задача для синхронизации данных WB за любой период
    
    Вызывайте через:
    - sync_tenant_wb_data.delay(tenant_id=1, date_from='2024-01-01', date_to='2024-01-07')
    - Из FastAPI эндпоинтов
    - Из других Celery задач
    - Из командной строки
    """
    db = SessionLocal()
    
    try:
        logger.info(f"🚀 Starting Celery task '{self.request.id}' for tenant {tenant_id}: {date_from} to {date_to}")
        
        # Обновляем статус задачи
        self.update_state(
            state='PROGRESS',
            meta={
                'tenant_id': tenant_id,
                'status': 'Starting sync...',
                'progress': 0
            }
        )
        
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            error_msg = f"Tenant {tenant_id} not found"
            logger.error(error_msg)
            self.update_state(
                state='FAILURE',
                meta={'error': error_msg}
            )
            return {'status': 'error', 'message': error_msg}
        
        if not tenant.wb_api_key:
            error_msg = f"WB API Key not configured for tenant {tenant_id}"
            logger.error(error_msg)
            self.update_state(
                state='FAILURE',
                meta={'error': error_msg}
            )
            return {'status': 'error', 'message': error_msg}
        
        self.update_state(
            state='PROGRESS',
            meta={
                'tenant_id': tenant_id,
                'status': 'Starting API sync...',
                'progress': 10
            }
        )
        
        # Запускаем универсальную синхронизацию
        sync_service = SyncService()
        
        metrics = asyncio.run(sync_service.sync_wb_data_for_period(
            db=db,
            tenant=tenant,
            date_from=date.fromisoformat(date_from),
            date_to=date.fromisoformat(date_to)
        ))
        
        logger.info(f"✅ Celery task '{self.request.id}' completed for tenant {tenant_id}")
        
        result = {
            'status': 'success',
            'task_id': self.request.id,
            'tenant_id': tenant_id,
            'period': f"{date_from} to {date_to}",
            'metrics': metrics,
            'completed_at': datetime.utcnow().isoformat()
        }
        
        self.update_state(
            state='SUCCESS',
            meta=result
        )
        
        return result
        
    except Exception as e:
        error_msg = f"Celery task failed for tenant {tenant_id}: {str(e)}"
        logger.error(error_msg)
        self.update_state(
            state='FAILURE',
            meta={'error': error_msg}
        )
        return {
            'status': 'error',
            'task_id': self.request.id,
            'tenant_id': tenant_id,
            'error': str(e),
            'failed_at': datetime.utcnow().isoformat()
        }
    finally:
        db.close()