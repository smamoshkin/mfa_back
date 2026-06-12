# routes/tax_rates.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date

from app.database.database import get_db
from app.schemas.tax_rate import TaxRate, TaxRateCreate, TaxRateUpdate, TaxRateCurrent
from app.crud.tax_rate_crud import (
    get_tax_rate, 
    get_tax_rates_by_tenant,
    get_current_tax_rate,
    get_tax_rate_by_date,
    create_tax_rate,
    update_tax_rate,
    delete_tax_rate,
    close_tax_rate_period,
    get_tax_rate_history
)
from app.routers.auth import get_current_tenant

router = APIRouter(
    prefix="/tax-rates",
    tags=["tax-rates"]
)

@router.post("/", response_model=TaxRate, status_code=status.HTTP_201_CREATED)
def create_tax_rate_endpoint(
    tax_rate: TaxRateCreate,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Создать новую налоговую ставку"""
    return create_tax_rate(db=db, tax_rate=tax_rate, tenant_id=current_tenant.id)

@router.get("/", response_model=List[TaxRate])
def get_tenant_tax_rates(
    skip: int = 0,
    limit: int = 100,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получить все налоговые ставки текущего tenant"""
    return get_tax_rates_by_tenant(
        db=db, 
        tenant_id=current_tenant.id, 
        skip=skip, 
        limit=limit
    )

@router.get("/current", response_model=TaxRateCurrent)
def get_current_tax_rate_endpoint(
    target_date: Optional[date] = Query(None, description="Дата для проверки (по умолчанию сегодня)"),
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получить текущую активную налоговую ставку"""
    tax_rate = get_current_tax_rate(db=db, tenant_id=current_tenant.id, target_date=target_date)
    
    if not tax_rate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Нет активной налоговой ставки на указанную дату"
        )
    
    return TaxRateCurrent(
        tax_rate=tax_rate.tax_rate,
        start_date=tax_rate.start_date,
        end_date=tax_rate.end_date,
        is_current=True
    )

@router.get("/date/{target_date}", response_model=TaxRate)
def get_tax_rate_by_date_endpoint(
    target_date: date,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получить налоговую ставку на конкретную дату"""
    tax_rate = get_tax_rate_by_date(
        db=db, 
        tenant_id=current_tenant.id, 
        target_date=target_date
    )
    
    if not tax_rate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Нет налоговой ставки на указанную дату"
        )
    
    return tax_rate

@router.get("/history", response_model=List[TaxRate])
def get_tax_rate_history_endpoint(
    date_from: Optional[date] = Query(None, description="Начало периода"),
    date_to: Optional[date] = Query(None, description="Конец периода"),
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получить историю налоговых ставок за период"""
    return get_tax_rate_history(
        db=db,
        tenant_id=current_tenant.id,
        date_from=date_from,
        date_to=date_to
    )

@router.get("/{tax_rate_id}", response_model=TaxRate)
def get_tax_rate_endpoint(
    tax_rate_id: int,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получить налоговую ставку по ID"""
    tax_rate = get_tax_rate(
        db=db, 
        tax_rate_id=tax_rate_id, 
        tenant_id=current_tenant.id
    )
    
    if not tax_rate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Налоговая ставка не найдена"
        )
    
    return tax_rate

@router.put("/{tax_rate_id}", response_model=TaxRate)
def update_tax_rate_endpoint(
    tax_rate_id: int,
    tax_rate: TaxRateUpdate,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Обновить налоговую ставку"""
    return update_tax_rate(
        db=db, 
        tax_rate_id=tax_rate_id, 
        tax_rate=tax_rate, 
        tenant_id=current_tenant.id
    )

@router.delete("/{tax_rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tax_rate_endpoint(
    tax_rate_id: int,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Удалить налоговую ставку"""
    deleted = delete_tax_rate(
        db=db, 
        tax_rate_id=tax_rate_id, 
        tenant_id=current_tenant.id
    )
    
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Налоговая ставка не найдена"
        )

@router.patch("/{tax_rate_id}/close", response_model=TaxRate)
def close_tax_rate_period_endpoint(
    tax_rate_id: int,
    end_date: date,
    current_tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Закрыть период действия налоговой ставки"""
    return close_tax_rate_period(
        db=db,
        tax_rate_id=tax_rate_id,
        end_date=end_date,
        tenant_id=current_tenant.id
    )