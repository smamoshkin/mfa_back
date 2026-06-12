from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Any
from datetime import date
from pydantic import BaseModel
from app.services.report_mapper import ReportMapperService
from app.database.database import get_db
from app.schemas.supplier_report import SupplierReport, SupplierReportCreate, ImportResult
from app.crud import supplier_report_crud
from app.routers.auth import get_current_tenant

class WBImportRequest(BaseModel):
    reports: List[Dict[str, Any]]

router = APIRouter(
    prefix="/supplier-reports",
    tags=["supplier-reports"]
)

@router.post("/bulk/", response_model=List[SupplierReport])
def bulk_create_reports(
    reports: List[SupplierReportCreate],
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    # 👇 УБИРАЕМ проверку - теперь CRUD сам устанавливает tenant_id
    try:
        return supplier_report_crud.bulk_create_reports(
            db=db, 
            reports=reports, 
            tenant_id=current_tenant.id  # 👈 Передаем tenant_id
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bulk create failed: {str(e)}"
        )

@router.get("/", response_model=List[SupplierReport])
def get_reports_by_tenant(
    skip: int = 0, 
    limit: int = 100,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    return supplier_report_crud.get_reports_by_tenant(
        db, tenant_id=current_tenant.id, skip=skip, limit=limit
    )

@router.get("/period/", response_model=List[SupplierReport])
def get_reports_by_period(
    date_from: date, 
    date_to: date,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    return supplier_report_crud.get_reports_by_period(
        db, tenant_id=current_tenant.id, date_from=date_from, date_to=date_to
    )

@router.get("/{report_id}", response_model=SupplierReport)
def get_supplier_report(
    report_id: int,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    # 👇 Используем защищенную версию с tenant_id
    db_report = supplier_report_crud.get_supplier_report(
        db, report_id=report_id, tenant_id=current_tenant.id
    )
    if db_report is None:
        raise HTTPException(status_code=404, detail="Supplier report not found")
    return db_report

@router.post("/import/wb/", response_model=ImportResult)  
def import_wb_reports(
    import_request: WBImportRequest,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Импорт отчетов из Wildberries API"""
    
    mapper = ReportMapperService()
    
    # 1. Преобразуем WB данные в наши модели
    reports_to_create = mapper.bulk_map_wb_reports(
        import_request.reports, 
        current_tenant.id
    )
    
    if not reports_to_create:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid reports to import"
        )
    
    # 2. Массово сохраняем с передачей tenant_id
    try:
        created_reports = supplier_report_crud.bulk_create_reports(
            db, 
            reports=reports_to_create, 
            tenant_id=current_tenant.id  # 👈 Передаем tenant_id
        )
        
        return ImportResult(
            imported_count=len(created_reports),
            total_received=len(import_request.reports),
            reports=created_reports
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}"
        )