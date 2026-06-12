# app/tasks/periodic_sync.py
from app.celery_app import celery_app
from app.database.database import SessionLocal
from app.models.tenant import Tenant
from datetime import datetime, date, timedelta
import logging

logger = logging.getLogger(__name__)

@celery_app.task(name='weekly_sync_all_tenants')
def weekly_sync_all_tenants():
    """
    Еженедельная синхронизация для всех активных tenant'ов
    """
    db = SessionLocal()
    try:
        logger.info("🔄 Starting weekly sync for all active tenants")
        
        # Получаем всех активных tenant'ов с WB API ключами
        active_tenants = db.query(Tenant).filter(
            Tenant.is_active == True,
            Tenant.wb_api_key.isnot(None),
            Tenant.wb_api_key != ''
        ).all()
        
        if not active_tenants:
            logger.info("ℹ️ No active tenants with WB API keys found")
            return {
                'status': 'skipped', 
                'reason': 'no_active_tenants',
                'timestamp': datetime.now().isoformat()
            }
        
        # Определяем период - последние 7 дней (прошлая неделя)
        end_date = date.today() - timedelta(days=1)  # Вчера (воскресенье)
        start_date = end_date - timedelta(days=6)    # 7 дней назад (понедельник)
        
        logger.info(f"📅 Sync period: {start_date} to {end_date}")
        
        # 👇 ИСПОЛЬЗУЕМ CELERY ЗАДАЧИ вместо прямого вызова
        from app.tasks.sync_tasks__old import sync_tenant_wb_data
        
        task_ids = {}
        for tenant in active_tenants:
            logger.info(f"🔄 Creating Celery task for tenant {tenant.id}...")
            try:
                # Запускаем синхронизацию как Celery задачу
                task = sync_tenant_wb_data.delay(
                    tenant_id=tenant.id,
                    date_from=start_date.isoformat(),
                    date_to=end_date.isoformat()
                )
                task_ids[tenant.id] = task.id
                logger.info(f"✅ Celery task created for tenant {tenant.id}: {task.id}")
            except Exception as e:
                logger.error(f"❌ Failed to create task for tenant {tenant.id}: {str(e)}")
                task_ids[tenant.id] = {'status': 'error', 'error': str(e)}
        
        return {
            'status': 'tasks_created',
            'task_count': len(active_tenants),
            'task_ids': task_ids,
            'period': f"{start_date} to {end_date}",
            'timestamp': datetime.now().isoformat(),
            'message': f"Created {len(task_ids)} Celery tasks. Check individual task status."
        }
        
    except Exception as e:
        logger.error(f"❌ Weekly sync failed: {str(e)}")
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }
    finally:
        db.close()