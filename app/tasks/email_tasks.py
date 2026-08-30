# app/tasks/email_tasks.py
"""
Celery-задачи отправки писем. Отправка блокирующая (smtplib), поэтому живёт
в воркере, а не в HTTP-хендлерах. Ретраи на случай недоступности SMTP.
"""
import logging

from app.celery_app import celery_app
from app.services import email_service

logger = logging.getLogger(__name__)


@celery_app.task(
    name="send_email_task",
    bind=True,
    max_retries=3,
    default_retry_delay=60,  # сек
)
def send_email_task(self, kind: str, to: str, token: str = ""):
    """
    kind: 'verification' | 'password_reset' | 'password_changed'
    """
    try:
        if kind == "verification":
            email_service.send_verification_email(to, token)
        elif kind == "password_reset":
            email_service.send_password_reset_email(to, token)
        elif kind == "password_changed":
            email_service.send_password_changed_email(to)
        else:
            logger.error(f"Unknown email kind: {kind}")
    except Exception as exc:
        logger.error(f"Email send failed ({kind} → {to}): {exc}")
        raise self.retry(exc=exc)
