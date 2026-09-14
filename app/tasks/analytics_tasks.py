# app/tasks/analytics_tasks.py
"""
Celery-задача полного пересчёта таблиц агрегатов аналитики (фолбэк/ops).

С 11.09.2026 (TODO №1) агрегаты — обычные таблицы
(supplier_reports_agg + product_margins), пересчёт по затронутым месяцам
делается синхронно в точках изменения данных (синк, налоговые ставки,
себестоимости, реклама) — он занимает миллисекунды. Эта Celery-задача —
ручной/аварийный инструмент: полный пересчёт ВСЕЙ истории тенанта
(например, после ручных правок данных в БД).
"""
import logging

from app.celery_app import celery_app
from app.database.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="recompute_analytics_task")
def recompute_analytics_task(tenant_id: int):
    """Полный пересчёт supplier_reports_agg + product_margins тенанта.

    months=None → вся история тенанта (единицы секунд). Идемпотентно.
    """
    from app.services.aggregates_service import recompute_analytics

    db = SessionLocal()
    try:
        stats = recompute_analytics(db, tenant_id)
        logger.info(f"✅ Full analytics recompute done | tenant={tenant_id} | {stats}")
        return {"status": "ok", "tenant_id": tenant_id, **stats}
    except Exception as e:
        logger.error(f"❌ Full analytics recompute failed | tenant={tenant_id}: {e}")
        return {"status": "error", "tenant_id": tenant_id, "error": str(e)}
    finally:
        db.close()
