from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from typing import Dict, Any
import logging

from app.database.database import get_db
from app.routers.auth import get_current_tenant
from app.services.analytics_service import AnalyticsService
from app.schemas.analytics import AnalyticsFilters
from app.services.report_generator import DynamicReport

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"]
)
logger = logging.getLogger(__name__)

@router.get("/rentability")
def get_rentability_report(
    date_from: date = Query(..., description="Start date for the report"),
    date_to: date = Query(..., description="End date for the report"),
    group_by: str = Query("month", description="Group by: day, week, month, quarter, year"),
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Полный отчет рентабельности за указанный период
    """
    try:
        analytics_service = AnalyticsService(db)
        report = analytics_service.get_rentability_report(
            tenant_id=current_tenant.id,
            date_from=date_from,
            date_to=date_to,
            group_by=group_by
        )
        
        return report
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating rentability report: {str(e)}"
        )

@router.get("/financial-overview")
def get_financial_overview(
    date_from: date = Query(..., description="Start date"),
    date_to: date = Query(..., description="End date"), 
    group_by: str = Query("month", description="Group by period"),
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Сводный финансовый отчет
    """
    analytics_service = AnalyticsService(db)
    # Можно добавить отдельный метод для финансового обзора
    return {"message": "Financial overview endpoint - to be implemented"}

@router.post("/export/excel")
async def export_analytics_excel(
    filters: AnalyticsFilters,
    current_user = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """
    Экспорт аналитики в Excel с формулами
    
    Пример запроса:
    {
        "date_from": "2024-01-01",
        "date_to": "2024-01-31",
        "group_by": "month",
        "sku": "optional_sku",
        "min_margin_percent": 10,
        "min_quantity": 5
    }
    """
    try:
        logger.info(f"Начало экспорта Excel для tenant_id={current_user.id}")
        
        # Валидация периода (например, не больше 1 года)
        _validate_export_period(filters.date_from, filters.date_to)
        
        # Подготавливаем фильтры
        export_filters = _prepare_filters(filters)
        
        # Генерируем отчет
        report_generator = DynamicReport(db)
        excel_file = report_generator.generate_excel_report(
            filters=export_filters,
            tenant_id=current_user.id
        )
        
        # Формируем имя файла
        filename = _generate_filename(filters)
        
        logger.info(f"Отчет сгенерирован: {filename}")
        
        return StreamingResponse(
            excel_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except ValueError as e:
        logger.error(f"Ошибка валидации: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Ошибка экспорта Excel: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка генерации отчета")

def _validate_export_period(date_from: date, date_to: date):
    """Валидация периода экспорта"""
    # Проверка, что дата начала раньше даты окончания
    if date_from > date_to:
        raise ValueError("Дата начала не может быть позже даты окончания")
    
    # Проверка максимального периода (например, 1 год)
    max_period = timedelta(days=365)
    if (date_to - date_from) > max_period:
        raise ValueError("Период экспорта не может превышать 1 год")
    
    # Проверка, что дата не в будущем
    # if date_to > datetime.now().date():
    #     raise ValueError("Дата окончания не может быть в будущем")

def _prepare_filters(filters: AnalyticsFilters) -> Dict[str, Any]:
    """Подготовка фильтров для генератора отчетов"""
    export_filters = {
        'date_from': filters.date_from,
        'date_to': filters.date_to,
    }
    
    # Добавляем дополнительные фильтры, если они заданы
    if hasattr(filters, 'group_by') and filters.group_by:
        export_filters['group_by'] = filters.group_by
        
    if hasattr(filters, 'sku') and filters.sku:
        export_filters['sku'] = filters.sku
        
    if hasattr(filters, 'min_margin_percent') and filters.min_margin_percent is not None:
        export_filters['min_margin_percent'] = filters.min_margin_percent
        
    if hasattr(filters, 'min_quantity') and filters.min_quantity is not None:
        export_filters['min_quantity'] = filters.min_quantity
        
    return export_filters

def _generate_filename(filters: AnalyticsFilters) -> str:
    """Генерация имени файла"""
    date_from_str = filters.date_from.strftime("%Y%m%d")
    date_to_str = filters.date_to.strftime("%Y%m%d")
    
    # Без русских символов
    return f"analytics_report_{date_from_str}_{date_to_str}.xlsx"