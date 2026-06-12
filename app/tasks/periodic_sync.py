# app/tasks/periodic_sync.py

import logging
from datetime import date, timedelta

from sqlalchemy import and_

from app.celery_app import celery_app
from app.database.database import SessionLocal
from app.models.tenant import Tenant
from app.services.sync_orchestrator import SyncOrchestrator, sync_orchestrator

logger = logging.getLogger(__name__)


@celery_app.task(name='run_weekly_sync_all_tenants')
def run_weekly_sync_all_tenants():
    """
    Запускается каждый понедельник в 06:00 MSK.
    Находит всех активных tenant с валидным WB ключом и completed initial sync.
    Запускает sync за прошлую неделю (пн → вс) для каждого.
    """
    from datetime import datetime, timezone

    db = SessionLocal()

    try:
        # --- Вычисляем диапазон прошлой недели ---
        week_start, week_end = SyncOrchestrator.get_last_week_range()

        logger.info(
            f"📅 Weekly sync started | period: {week_start} → {week_end}"
        )

        # --- Выбираем кандидатов ---
        now = datetime.now(timezone.utc)

        tenants = (
            db.query(Tenant)
            .filter(
                and_(
                    Tenant.is_active == True,
                    Tenant.sync_enabled == True,
                    Tenant.needs_initial_sync == False,  # initial sync завершён
                    Tenant.wb_api_key != None,
                    Tenant.wb_api_key != "",
                    # Токен не просрочен (или срок не задан)
                    (Tenant.wb_api_key_expire_at == None) |
                    (Tenant.wb_api_key_expire_at > now),
                    # Не в процессе другой синхронизации
                    Tenant.last_sync_status.notin_(["queued", "running"]),
                )
            )
            .all()
        )

        total = len(tenants)
        launched = 0
        skipped = 0
        failed = 0

        logger.info(f"📋 Found {total} tenants eligible for weekly sync")

        # --- Запускаем sync для каждого ---
        for tenant in tenants:
            try:
                job = sync_orchestrator.create_and_launch_weekly_sync(
                    db=db,
                    tenant=tenant,
                    week_start=week_start,
                    week_end=week_end,
                )

                if job:
                    launched += 1
                    logger.info(
                        f"✅ Weekly sync launched | "
                        f"tenant={tenant.id} | job_id={job.id}"
                    )
                else:
                    skipped += 1
                    logger.info(
                        f"⏭️ Tenant {tenant.id} skipped by orchestrator"
                    )

            except Exception as e:
                failed += 1
                logger.error(
                    f"❌ Failed to launch weekly sync for tenant {tenant.id}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"📊 Weekly sync summary | "
            f"total={total} | launched={launched} | "
            f"skipped={skipped} | failed={failed} | "
            f"period={week_start} → {week_end}"
        )

        return {
            "period": f"{week_start} → {week_end}",
            "total_tenants": total,
            "launched": launched,
            "skipped": skipped,
            "failed": failed,
        }

    except Exception as e:
        logger.error(f"❌ Weekly sync job failed critically: {e}", exc_info=True)
        raise

    finally:
        db.close()


@celery_app.task(name='run_initial_sync_pending_tenants')
def run_initial_sync_pending_tenants():
    """
    Вспомогательная задача — запускается раз в час.
    Подхватывает tenant у которых initial sync завис в статусе 'queued'
    дольше 30 минут (например Celery был недоступен при добавлении токена).
    """
    from datetime import datetime, timezone, timedelta

    db = SessionLocal()

    try:
        from app.models.tenant_sync_job import TenantSyncJob
        from sqlalchemy import and_

        threshold = datetime.now(timezone.utc) - timedelta(minutes=30)

        # Ищем зависшие initial sync jobs
        stalled_jobs = (
            db.query(TenantSyncJob)
            .filter(
                and_(
                    TenantSyncJob.sync_type == "initial",
                    TenantSyncJob.status == "queued",
                    TenantSyncJob.created_at < threshold,
                )
            )
            .all()
        )

        if not stalled_jobs:
            return {"stalled": 0, "restarted": 0}

        logger.warning(f"⚠️ Found {len(stalled_jobs)} stalled initial sync jobs")

        restarted = 0
        for job in stalled_jobs:
            try:
                tenant = db.query(Tenant).filter(
                    Tenant.id == job.tenant_id
                ).first()

                if not tenant or not tenant.wb_api_key:
                    continue

                # Помечаем старый job как failed
                from app.crud import sync_job_crud
                sync_job_crud.mark_job_failed(
                    db, job.id,
                    "Job stalled in queued state for 30+ minutes, restarting"
                )
                sync_job_crud.update_tenant_sync_state(db, tenant.id, job)

                # Перезапускаем
                new_job = sync_orchestrator.create_and_launch_initial_sync(
                    db=db,
                    tenant=tenant,
                    triggered_by="system",
                )

                if new_job:
                    restarted += 1
                    logger.info(
                        f"🔄 Restarted stalled initial sync | "
                        f"tenant={tenant.id} | old_job={job.id} | new_job={new_job.id}"
                    )

            except Exception as e:
                logger.error(
                    f"❌ Failed to restart stalled job {job.id}: {e}",
                    exc_info=True,
                )

        return {"stalled": len(stalled_jobs), "restarted": restarted}

    finally:
        db.close()