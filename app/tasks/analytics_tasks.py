# app/tasks/analytics_tasks.py
"""
Celery-задачи пересчёта материализованных view аналитики.

REFRESH мат.view занимает секунды (пересчёт агрегатов по всей
supplier_reports), поэтому из HTTP-хендлеров — CRUD налоговых ставок и
импорт себестоимостей — он запускается АСИНХРОННО: интерфейс не ждёт,
агрегаты обновляются фоном (~10 секунд). До появления этой задачи прямой
вызов из CRUD налоговых ставок замедлял ответ интерфейса на те же секунды.

Идемпотентность: повторный REFRESH безвреден (пересчёт того же состояния);
если задача потерялась (рестарт воркера), агрегаты обновит следующий синк
или следующее изменение ставки.
"""
import logging

from app.celery_app import celery_app
from app.services.sync_service import refresh_analytics_materialized_views

logger = logging.getLogger(__name__)


@celery_app.task(name="refresh_analytics_materialized_views_task")
def refresh_analytics_materialized_views_task():
    """Фоновый REFRESH supplier_reports_agg_mv + product_margins_mv.

    Функция refresh_analytics_materialized_views() глотает ошибки сама
    (логирует warning и возвращает время) — ретраи не нужны: агрегаты
    просто останутся на прошлом снапшоте до следующего обновления.
    """
    elapsed_ms = refresh_analytics_materialized_views()
    logger.info(f"✅ Background analytics MV refresh done in {elapsed_ms}ms")
    return {"status": "ok", "elapsed_ms": elapsed_ms}
