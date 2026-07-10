from sqlalchemy.orm import Session
from sqlalchemy import insert
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

def bulk_create_reports_DEBUG(db: Session, reports: List[SupplierReportCreate], tenant_id: int):
    """ДЕТАЛЬНАЯ ДИАГНОСТИКА ВРЕМЕНИ"""
    if not reports:
        return []
    
    logger.info(f"⏱️  DEBUG: Starting bulk_insert with {len(reports)} reports")
    
    reports_data = []
    for report in reports:
        report_data = report.model_dump()
        report_data['tenant_id'] = tenant_id
        reports_data.append(report_data)
    
    total_inserted = 0
    batch_size = 10000

    try:
        for i in range(0, len(reports_data), batch_size):
            batch = reports_data[i:i + batch_size]
            batch_num = (i // batch_size) + 1

            logger.info(f"⏱️  DEBUG Batch {batch_num}: Starting...")

            prepare_time = time.time()
            stmt = insert(SupplierReport).values(batch)
            prepare_time = time.time() - prepare_time

            execute_time = time.time()
            db.execute(stmt)
            execute_time = time.time() - execute_time

            commit_time = time.time()
            db.commit()
            commit_time = time.time() - commit_time

            total_batch_time = prepare_time + execute_time + commit_time
            total_inserted += len(batch)

            logger.info(f"⏱️  DEBUG Batch {batch_num} TIMING:")
            logger.info(f"⏱️    - Prepare: {prepare_time:.2f}s")
            logger.info(f"⏱️    - Execute: {execute_time:.2f}s")
            logger.info(f"⏱️    - Commit: {commit_time:.2f}s")
            logger.info(f"⏱️    - Total: {total_batch_time:.2f}s")
            logger.info(f"⏱️    - Speed: {len(batch)/execute_time:.1f} records/sec")

        return total_inserted
        
    except Exception as e:
        logger.error(f"❌ Bulk insert failed: {str(e)}")
        db.rollback()
        raise