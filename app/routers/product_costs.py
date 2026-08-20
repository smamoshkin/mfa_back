from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import date
import os

from app.database.database import get_db
from app.schemas.product_cost import (
    ProductCost, ProductCostCreate, ProductCostUpdate,
    CostImportReport,
)
from app.crud import product_cost_crud
from app.routers.auth import get_current_tenant
from app.models.product import Product
from app.services.cost_import_service import (
    CostImportService, CostImportError, ALLOWED_EXTENSIONS,
)

router = APIRouter(
    prefix="/product-costs",
    tags=["product-costs"]
)

@router.post("/", response_model=ProductCost, status_code=status.HTTP_201_CREATED)
def create_product_cost(
    cost: ProductCostCreate, 
    current_tenant = Depends(get_current_tenant), 
    db: Session = Depends(get_db)
):

    try:
        return product_cost_crud.create_product_cost(db=db, cost=cost, tenant_id=current_tenant.id)
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database constraint violation"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/template")
def download_cost_template(
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    xlsx-шаблон себестоимостей с префиллом: все товары тенанта,
    текущие себестоимости и даты их начала. Для раундтрипа:
    скачать → править → загрузить через /import.
    """
    service = CostImportService(db)
    buf = service.generate_template(current_tenant.id)
    filename = f"product_costs_template_{date.today().strftime('%Y%m%d')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

@router.post("/import", response_model=CostImportReport)
async def import_costs(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Импорт себестоимостей из xlsx/csv (колонки: sku, cost, start_date).

    dry_run=True (умолчание) — только предпросмотр: отчёт по строкам
    (create/update/error) без записи в БД.
    dry_run=False — применяет импорт: обновляет совпадающие по дате записи,
    создаёт новые, пересегментирует периоды и обновляет мат.view аналитики.
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый формат файла '{ext}'. Ожидаются: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл пуст",
        )

    service = CostImportService(db)
    try:
        return service.process(
            tenant_id=current_tenant.id,
            data=data,
            filename=file.filename,
            dry_run=dry_run,
        )
    except CostImportError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка импорта себестоимостей: {str(e)}",
        )

@router.get("/product/{product_id}"
            , response_model=List[ProductCost] #- убираем, потому что модель может вернуть None в случае отсутствия данных, а надо вернуть 200 с null в теле ответа
            )
def get_costs_by_product(
    product_id: int, 
    skip: int = 0, 
    limit: int = 100, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    return product_cost_crud.get_costs_by_product(db, product_id=product_id, tenant_id=current_tenant.id, skip=skip, limit=limit)

@router.get("/product/{product_id}/current" 
                , response_model=Optional[ProductCost] #- убираем, потому что модель может вернуть None в случае отсутствия данных, а надо вернуть 200 с null в теле ответа
                )
def get_current_cost(
    product_id: int, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    cost = product_cost_crud.get_current_cost(db, product_id=product_id, tenant_id=current_tenant.id)
    # if not cost:
    #     raise None  # Это вернет 200 с null в теле ответа
    return cost

@router.get("/product/{product_id}/date/{target_date}", response_model=ProductCost)
def get_cost_by_date(
    product_id: int, 
    target_date: date, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    cost = product_cost_crud.get_cost_by_date(db, product_id=product_id, target_date=target_date, tenant_id=current_tenant.id)
    if not cost:
        raise HTTPException(status_code=404, detail="No cost found for this date")
    return cost

@router.get("/{cost_id}", response_model=ProductCost)
def get_product_cost(
    cost_id: int, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    db_cost = product_cost_crud.get_product_cost(db, cost_id=cost_id, tenant_id=current_tenant.id)
    if db_cost is None:
        raise HTTPException(status_code=404, detail="Product cost not found")
    return db_cost

@router.put("/{cost_id}", response_model=ProductCost)
def update_product_cost(
    cost_id: int, 
    cost: ProductCostUpdate, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    try:
        db_cost = product_cost_crud.update_product_cost(db, cost_id=cost_id, cost=cost, tenant_id=current_tenant.id)
        if db_cost is None:
            raise HTTPException(status_code=404, detail="Product cost not found")
        return db_cost
    except HTTPException:
        raise

@router.delete("/{cost_id}")
def delete_product_cost(
    cost_id: int, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    db_cost = product_cost_crud.delete_product_cost(db, cost_id=cost_id, tenant_id=current_tenant.id)
    if db_cost is None:
        raise HTTPException(status_code=404, detail="Product cost not found")
    return {"message": "Product cost deleted successfully"}

@router.patch("/{cost_id}/close")
def close_cost_period(
    cost_id: int, 
    end_date: date, 
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    try:
        return product_cost_crud.close_cost_period(db, cost_id=cost_id, end_date=end_date, tenant_id=current_tenant.id)
    except HTTPException:
        raise