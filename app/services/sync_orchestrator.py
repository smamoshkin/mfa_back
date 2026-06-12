# app/services/sync_orchestrator.py

import logging
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.tenant_sync_job import TenantSyncJob
from app.crud import sync_job_crud

logger = logging.getLogger(__name__)

# Дата начала исторической загрузки — фиксирована для initial sync
INITIAL_SYNC_DATE_FROM = date(2024, 12, 29)


class SyncOrchestrator:

    # -----------------------------------------------------------------------
    # ПРОВЕРКИ — можно ли запускать
    # -----------------------------------------------------------------------

    def can_start_sync(self, db: Session, tenant_id: int) -> tuple[bool, str]:
        """
        Проверяет, можно ли запустить новый sync для tenant.
        Возвращает (True, "") или (False, причина).
        """
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return False, f"Tenant {tenant_id} not found"

        if not tenant.is_active:
            return False, "Tenant is not active"

        if not tenant.sync_enabled:
            return False, "Sync is disabled for this tenant"

        if not tenant.wb_api_key:
            return False, "WB API key is not configured"

        if tenant.wb_api_key_expire_at:
            expire_at = tenant.wb_api_key_expire_at
            if expire_at.tzinfo is None:
                expire_at = expire_at.replace(tzinfo=timezone.utc)
            if expire_at < datetime.now(timezone.utc):
                return False, "WB API key has expired"

        if sync_job_crud.is_sync_running(db, tenant_id):
            return False, "Sync is already running for this tenant"

        return True, ""

    def needs_initial_sync(self, db: Session, tenant_id: int) -> bool:
        """
        True если у tenant ещё не было успешного initial sync.
        """
        return not sync_job_crud.has_completed_initial_sync(db, tenant_id)

    # -----------------------------------------------------------------------
    # ЗАПУСК — initial sync
    # -----------------------------------------------------------------------

    def create_and_launch_initial_sync(
        self,
        db: Session,
        tenant: Tenant,
        triggered_by: str = "system",
    ) -> Optional[TenantSyncJob]:
        """
        Создаёт job и ставит Celery task для initial sync.
        Диапазон: INITIAL_SYNC_DATE_FROM → сегодня.

        Возвращает созданный job или None если запуск невозможен.
        """
        # Импорт здесь, чтобы избежать циклических зависимостей
        from app.tasks.sync_tasks import sync_tenant_wb_data

        can_run, reason = self.can_start_sync(db, tenant.id)
        if not can_run:
            logger.warning(
                f"Cannot start initial sync for tenant {tenant.id}: {reason}"
            )
            return None

        if not self.needs_initial_sync(db, tenant.id):
            logger.info(
                f"Tenant {tenant.id} already has completed initial sync, skipping"
            )
            return None

        date_from = datetime.combine(INITIAL_SYNC_DATE_FROM, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        date_to = datetime.combine(date.today(), datetime.max.time()).replace(
            tzinfo=timezone.utc
        )

        # Создаём job в БД
        job = sync_job_crud.create_sync_job(
            db=db,
            tenant_id=tenant.id,
            sync_type="initial",
            date_from=date_from,
            date_to=date_to,
            triggered_by=triggered_by,
        )

        # Обновляем tenant: помечаем что initial sync запрошен
        tenant.needs_initial_sync = True
        tenant.last_sync_status = "queued"
        tenant.last_sync_run_id = job.id
        db.commit()

        # Ставим Celery task
        try:
            task = sync_tenant_wb_data.delay(
                tenant_id=tenant.id,
                date_from=INITIAL_SYNC_DATE_FROM.isoformat(),
                date_to=date.today().isoformat(),
                sync_type="initial",
                job_id=job.id,
            )
            logger.info(
                f"🚀 Initial sync launched for tenant {tenant.id}, "
                f"job_id={job.id}, task_id={task.id}"
            )
        except Exception as e:
            # Если Celery недоступен — помечаем job как failed
            logger.error(
                f"❌ Failed to launch Celery task for tenant {tenant.id}: {e}"
            )
            sync_job_crud.mark_job_failed(db, job.id, str(e))
            sync_job_crud.update_tenant_sync_state(db, tenant.id, job)
            return job

        return job

    # -----------------------------------------------------------------------
    # ЗАПУСК — weekly sync
    # -----------------------------------------------------------------------

    def create_and_launch_weekly_sync(
        self,
        db: Session,
        tenant: Tenant,
        week_start: date,
        week_end: date,
    ) -> Optional[TenantSyncJob]:
        """
        Создаёт job и ставит Celery task для weekly sync.
        Вызывается из планировщика каждый понедельник.
        """
        from app.tasks.sync_tasks import sync_tenant_wb_data

        can_run, reason = self.can_start_sync(db, tenant.id)
        if not can_run:
            logger.warning(
                f"Cannot start weekly sync for tenant {tenant.id}: {reason}"
            )
            return None

        # Для weekly — требуем завершённый initial sync
        if self.needs_initial_sync(db, tenant.id):
            logger.warning(
                f"Tenant {tenant.id} has no completed initial sync, "
                f"skipping weekly sync"
            )
            return None

        date_from = datetime.combine(week_start, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        date_to = datetime.combine(week_end, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )

        job = sync_job_crud.create_sync_job(
            db=db,
            tenant_id=tenant.id,
            sync_type="weekly",
            date_from=date_from,
            date_to=date_to,
            triggered_by="scheduler",
        )

        tenant.last_sync_status = "queued"
        tenant.last_sync_run_id = job.id
        db.commit()

        try:
            task = sync_tenant_wb_data.delay(
                tenant_id=tenant.id,
                date_from=week_start.isoformat(),
                date_to=week_end.isoformat(),
                sync_type="weekly",
                job_id=job.id,
            )
            logger.info(
                f"🗓️ Weekly sync launched for tenant {tenant.id}, "
                f"job_id={job.id}, task_id={task.id}, "
                f"period={week_start} → {week_end}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to launch weekly Celery task for tenant {tenant.id}: {e}"
            )
            sync_job_crud.mark_job_failed(db, job.id, str(e))
            sync_job_crud.update_tenant_sync_state(db, tenant.id, job)
            return job

        return job

    # -----------------------------------------------------------------------
    # ЗАПУСК — ручной sync (из UI)
    # -----------------------------------------------------------------------

    def create_and_launch_manual_sync(
        self,
        db: Session,
        tenant: Tenant,
        date_from: date,
        date_to: date,
    ) -> Optional[TenantSyncJob]:
        """
        Ручной запуск синхронизации за произвольный период из UI.
        """
        from app.tasks.sync_tasks import sync_tenant_wb_data

        can_run, reason = self.can_start_sync(db, tenant.id)
        if not can_run:
            logger.warning(
                f"Cannot start manual sync for tenant {tenant.id}: {reason}"
            )
            return None, reason

        dt_from = datetime.combine(date_from, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        dt_to = datetime.combine(date_to, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )

        job = sync_job_crud.create_sync_job(
            db=db,
            tenant_id=tenant.id,
            sync_type="manual",
            date_from=dt_from,
            date_to=dt_to,
            triggered_by="user",
        )

        tenant.last_sync_status = "queued"
        tenant.last_sync_run_id = job.id
        db.commit()

        try:
            task = sync_tenant_wb_data.delay(
                tenant_id=tenant.id,
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                sync_type="manual",
                job_id=job.id,
            )
            logger.info(
                f"🖐️ Manual sync launched for tenant {tenant.id}, "
                f"job_id={job.id}, task_id={task.id}"
            )
        except Exception as e:
            logger.error(
                f"❌ Failed to launch manual Celery task for tenant {tenant.id}: {e}"
            )
            sync_job_crud.mark_job_failed(db, job.id, str(e))
            sync_job_crud.update_tenant_sync_state(db, tenant.id, job)
            return job, str(e)

        return job, None

    # -----------------------------------------------------------------------
    # CALLBACKS — вызываются из Celery task
    # -----------------------------------------------------------------------

    def on_sync_started(
        self,
        db: Session,
        job_id: int,
        task_id: str,
    ) -> None:
        """
        Вызывается в начале Celery task.
        Обновляет job и tenant.
        """
        job = sync_job_crud.mark_job_running(db, job_id, task_id)
        if job:
            sync_job_crud.update_tenant_sync_state(db, job.tenant_id, job)
            logger.info(f"▶️ Sync started: job_id={job_id}, task_id={task_id}")

    def on_sync_success(
        self,
        db: Session,
        job_id: int,
        metrics: dict,
    ) -> None:
        """
        Вызывается после успешного завершения Celery task.
        Обновляет job, сохраняет метрики, обновляет tenant.
        """
        job = sync_job_crud.mark_job_success(db, job_id, metrics)
        if job:
            sync_job_crud.update_tenant_sync_state(db, job.tenant_id, job)
            logger.info(
                f"✅ Sync succeeded: job_id={job_id}, "
                f"records={metrics.get('total_records')}, "
                f"products={metrics.get('products_synced')}"
            )

    def on_sync_failed(
        self,
        db: Session,
        job_id: int,
        error: str,
    ) -> None:
        """
        Вызывается при ошибке в Celery task.
        Обновляет job и tenant.
        """
        job = sync_job_crud.mark_job_failed(db, job_id, error)
        if job:
            sync_job_crud.update_tenant_sync_state(db, job.tenant_id, job)
            logger.error(f"❌ Sync failed: job_id={job_id}, error={error}")

    # -----------------------------------------------------------------------
    # УТИЛИТА — вычисление прошлой недели для weekly sync
    # -----------------------------------------------------------------------

    @staticmethod
    def get_last_week_range() -> tuple[date, date]:
        """
        Возвращает (понедельник, воскресенье) прошлой недели.
        Используется в планировщике каждый понедельник.
        """
        today = date.today()
        # Текущий понедельник
        current_monday = today - timedelta(days=today.weekday())
        # Прошлый понедельник
        last_monday = current_monday - timedelta(weeks=1)
        # Прошлое воскресенье
        last_sunday = last_monday + timedelta(days=6)
        return last_monday, last_sunday


# Синглтон для использования во всём приложении
sync_orchestrator = SyncOrchestrator()