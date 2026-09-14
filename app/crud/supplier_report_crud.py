from sqlalchemy.orm import Session
from sqlalchemy import insert, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from fastapi import HTTPException, status
from app.models.supplier_report import SupplierReport
from app.models.tenant import Tenant
from app.schemas.supplier_report import SupplierReportCreate
from typing import List
from datetime import date
import logging
import time

logger = logging.getLogger(__name__)

def get_supplier_report(db: Session, report_id: int, tenant_id: int = None):
    """Получить отчет по ID с проверкой прав"""
    query = db.query(SupplierReport).filter(SupplierReport.id == report_id)
    if tenant_id is not None:
        query = query.filter(SupplierReport.tenant_id == tenant_id)
    return query.first()

def get_reports_by_tenant(db: Session, tenant_id: int, skip: int = 0, limit: int = 100):
    """Получить все отчеты tenant'а"""
    return db.query(SupplierReport).filter(
        SupplierReport.tenant_id == tenant_id
    ).order_by(
        SupplierReport.sale_dt.desc()
    ).offset(skip).limit(limit).all()

def get_reports_by_period(db: Session, tenant_id: int, date_from: date, date_to: date):
    """Получить отчеты за период"""
    return db.query(SupplierReport).filter(
        SupplierReport.tenant_id == tenant_id,
        SupplierReport.sale_dt >= date_from,
        SupplierReport.sale_dt <= date_to
    ).order_by(SupplierReport.sale_dt).all()

def create_supplier_report(db: Session, report: SupplierReportCreate, tenant_id: int):
    """Создать новый отчет с принудительным tenant_id"""
    # Перезаписываем tenant_id из аутентификации
    report_data = report.model_dump()
    report_data['tenant_id'] = tenant_id
    
    # Проверяем уникальность rrd_id в рамках tenant'а
    if report.rrd_id:
        existing_report = db.query(SupplierReport).filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.rrd_id == report.rrd_id
        ).first()
        if existing_report:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Report with this rrd_id already exists"
            )
    
    db_report = SupplierReport(**report_data)
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report

def bulk_create_reports(db: Session, reports: List[SupplierReportCreate], tenant_id: int):
    """Идемпотентная пакетная вставка отчётов WB (TODO №2).

    UNIQUE (tenant_id, rrd_id): повторная загрузка того же периода НЕ создаёт
    дублей — конфликт обновляет все мутируемые поля (WB правит sale_dt и суммы
    у старых строк). Строки с rrd_id = NULL не конфликтуют никогда (просто
    вставляются). Возвращает число обработанных записей; вставлено/обновлено —
    в логах (inserted/updated).

    Требует уник-индекс uq_supplier_reports_tenant_rrd
    (db/scripts/02_unique_supplier_reports_rrd.sql).
    """
    if not reports:
        return 0

    logger.info(f"💾 Bulk upsert: {len(reports)} reports for tenant {tenant_id}")

    reports_data = []
    for report in reports:
        report_data = report.model_dump()
        report_data['tenant_id'] = tenant_id
        reports_data.append(report_data)

    # Мутируемые поля upsert: всё, кроме PK id, ключа конфликта (tenant_id, rrd_id),
    # created_at и GENERATED-колонок (period_month считает сама БД — её нельзя
    # ни вставлять, ни обновлять)
    updatable_columns = [
        c.name for c in SupplierReport.__table__.columns
        if c.name not in ('id', 'tenant_id', 'rrd_id', 'created_at')
        and c.computed is None
    ]

    total_processed = 0
    total_inserted = 0
    total_updated = 0
    batch_size = 10000

    try:
        for i in range(0, len(reports_data), batch_size):
            batch = reports_data[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            batch_time = time.time()

            stmt = pg_insert(SupplierReport).values(batch)
            # В SET — EXCLUDED (предлагаемые значения): ссылка на имя таблицы
            # означала бы СТАРОЕ значение строки, и upsert превратился бы в no-op
            stmt = stmt.on_conflict_do_update(
                index_elements=['tenant_id', 'rrd_id'],
                set_={col: stmt.excluded[col] for col in updatable_columns},
            ).returning(literal_column('(xmax = 0)').label('inserted'))

            flags = db.execute(stmt).scalars().all()
            db.commit()

            inserted = sum(1 for f in flags if f in (True, 't', 'true'))
            updated = len(flags) - inserted
            total_processed += len(batch)
            total_inserted += inserted
            total_updated += updated

            logger.info(
                f"💾 Bulk upsert batch {batch_num}: {len(batch)} rows "
                f"({len(batch)/(time.time() - batch_time):.1f} rec/s) | "
                f"inserted={inserted}, updated={updated}"
            )

        logger.info(
            f"✅ Bulk upsert done: processed={total_processed}, "
            f"inserted={total_inserted}, updated={total_updated}"
        )
        return total_processed

    except Exception as e:
        logger.error(f"❌ Bulk upsert failed: {str(e)}")
        db.rollback()
        raise


# Обратная совместимость: старое имя функции (синк-сервис и роутеры)
bulk_create_reports_DEBUG = bulk_create_reports