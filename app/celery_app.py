# app/celery_app.py

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Создаём Celery приложение
# ---------------------------------------------------------------------------

celery_app = Celery(
    'marketfinance',
    broker='redis://94.103.91.204:6379/0',
    backend='redis://94.103.91.204:6379/0',
    include=[
        'app.tasks.sync_tasks',
        'app.tasks.periodic_sync',   # регистрируем periodic задачи
    ]
)

# ---------------------------------------------------------------------------
# Основная конфигурация
# ---------------------------------------------------------------------------

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Europe/Moscow',
    enable_utc=True,
)

# ---------------------------------------------------------------------------
# Celery Beat — расписание периодических задач
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {

    # Еженедельная синхронизация — каждый понедельник в 06:00 MSK
    'weekly-wb-sync': {
        'task': 'run_weekly_sync_all_tenants',
        'schedule': crontab(hour=10, minute=0, day_of_week=1),
    },

    # Подхват зависших initial sync — каждый час в :00
    'retry-stalled-initial-sync': {
        'task': 'run_initial_sync_pending_tenants',
        'schedule': crontab(minute=0),
    },
}

# Beat не запускает одну задачу дважды одновременно
celery_app.conf.beat_max_loop_interval = 5