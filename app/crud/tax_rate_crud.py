# crud/tax_rate_crud.py
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from fastapi import HTTPException, status
from decimal import Decimal
from typing import Optional

from app.models.tax_rate import TaxRate
from app.models.tenant import Tenant
from app.schemas.tax_rate import TaxRateCreate, TaxRateUpdate

def get_tax_rate(db: Session, tax_rate_id: int, tenant_id: int):
    """Получить налоговую ставку по ID"""
    return db.query(TaxRate).filter(
        TaxRate.id == tax_rate_id,
        TaxRate.tenant_id == tenant_id
    ).first()

def get_tax_rates_by_tenant(db: Session, tenant_id: int, skip: int = 0, limit: int = 100):
    """Получить все налоговые ставки для tenant"""
    return db.query(TaxRate).filter(
        TaxRate.tenant_id == tenant_id
    ).order_by(
        TaxRate.start_date.desc()
    ).offset(skip).limit(limit).all()

def get_current_tax_rate(db: Session, tenant_id: int, target_date: date = None):
    """Получить текущую активную налоговую ставку"""
    if target_date is None:
        target_date = date.today()
    
    return db.query(TaxRate).filter(
        TaxRate.tenant_id == tenant_id,
        TaxRate.start_date <= target_date,
        or_(
            TaxRate.end_date.is_(None),
            TaxRate.end_date >= target_date
        )
    ).order_by(
        TaxRate.start_date.desc()
    ).first()

def get_tax_rate_by_date(db: Session, tenant_id: int, target_date: date):
    """Получить налоговую ставку на конкретную дату"""
    return db.query(TaxRate).filter(
        TaxRate.tenant_id == tenant_id,
        TaxRate.start_date <= target_date,
        or_(
            TaxRate.end_date.is_(None),
            TaxRate.end_date >= target_date
        )
    ).order_by(
        TaxRate.start_date.desc()
    ).first()

def check_tax_rate_overlap(
    db: Session, 
    tenant_id: int, 
    start_date: date, 
    end_date: Optional[date], 
    exclude_id: int = None
):
    """
    Проверить пересечение периодов налоговых ставок
    
    Возвращает True если есть пересечение, False если нет
    """
    query = db.query(TaxRate).filter(
        TaxRate.tenant_id == tenant_id
    )
    
    if exclude_id:
        query = query.filter(TaxRate.id != exclude_id)
    
    if end_date:
        # Проверяем пересечение для периода с end_date
        overlapping = query.filter(
            or_(
                # Случай 1: Новый период начинается внутри существующего
                and_(
                    TaxRate.start_date <= start_date,
                    or_(
                        TaxRate.end_date.is_(None),
                        TaxRate.end_date >= start_date
                    )
                ),
                # Случай 2: Новый период заканчивается внутри существующего
                and_(
                    TaxRate.start_date <= end_date,
                    or_(
                        TaxRate.end_date.is_(None),
                        TaxRate.end_date >= end_date
                    )
                ),
                # Случай 3: Новый период охватывает существующий
                and_(
                    start_date <= TaxRate.start_date,
                    end_date >= TaxRate.end_date
                ),
                # Случай 4: Существующий период охватывает новый
                and_(
                    TaxRate.start_date <= start_date,
                    or_(
                        TaxRate.end_date.is_(None),
                        TaxRate.end_date >= end_date
                    )
                )
            )
        ).first()
    else:
        # Проверяем пересечение для бесконечного периода (без end_date)
        overlapping = query.filter(
            or_(
                # Существующий начинается после нового start_date
                TaxRate.start_date >= start_date,
                # Существующий тоже бесконечный
                TaxRate.end_date.is_(None),
                # Существующий заканчивается после нового start_date
                and_(
                    TaxRate.end_date.isnot(None),
                    TaxRate.end_date >= start_date
                )
            )
        ).first()
    
    return overlapping is not None

def create_tax_rate(db: Session, tax_rate: TaxRateCreate, tenant_id: int):
    """Создать новую налоговую ставку"""
    
    # Проверяем пересечение периодов
    if check_tax_rate_overlap(
        db=db,
        tenant_id=tenant_id,
        start_date=tax_rate.start_date,
        end_date=tax_rate.end_date
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Налоговая ставка пересекается с существующим периодом"
        )
    
    # Создаем новую запись
    db_tax_rate = TaxRate(
        **tax_rate.model_dump(),
        tenant_id=tenant_id
    )
    db.add(db_tax_rate)
    db.commit()
    db.refresh(db_tax_rate)
    
    return db_tax_rate

def update_tax_rate(db: Session, tax_rate_id: int, tax_rate: TaxRateUpdate, tenant_id: int):
    """Обновить налоговую ставку"""
    db_tax_rate = get_tax_rate(db, tax_rate_id=tax_rate_id, tenant_id=tenant_id)
    if not db_tax_rate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Налоговая ставка не найдена"
        )
    
    # Получаем обновленные значения
    update_data = tax_rate.model_dump(exclude_unset=True)
    
    # Если обновляется start_date или end_date, проверяем пересечение
    if 'start_date' in update_data or 'end_date' in update_data:
        new_start = update_data.get('start_date', db_tax_rate.start_date)
        new_end = update_data.get('end_date', db_tax_rate.end_date)
        
        if check_tax_rate_overlap(
            db=db,
            tenant_id=tenant_id,
            start_date=new_start,
            end_date=new_end,
            exclude_id=tax_rate_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Обновленные даты пересекаются с существующим периодом"
            )
    
    # Применяем обновления
    for field, value in update_data.items():
        setattr(db_tax_rate, field, value)
    
    db.commit()
    db.refresh(db_tax_rate)
    return db_tax_rate

def delete_tax_rate(db: Session, tax_rate_id: int, tenant_id: int):
    """Удалить налоговую ставку"""
    db_tax_rate = get_tax_rate(db, tax_rate_id=tax_rate_id, tenant_id=tenant_id)
    if not db_tax_rate:
        return None
    
    db.delete(db_tax_rate)
    db.commit()
    return db_tax_rate

def close_tax_rate_period(db: Session, tax_rate_id: int, end_date: date, tenant_id: int):
    """Закрыть период действия налоговой ставки"""
    db_tax_rate = get_tax_rate(db, tax_rate_id=tax_rate_id, tenant_id=tenant_id)
    if not db_tax_rate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Налоговая ставка не найдена"
        )
    
    # Проверяем что end_date >= start_date
    if end_date < db_tax_rate.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Дата окончания не может быть раньше даты начала"
        )
    
    db_tax_rate.end_date = end_date
    db.commit()
    db.refresh(db_tax_rate)
    return db_tax_rate

def get_tax_rate_history(db: Session, tenant_id: int, date_from: date = None, date_to: date = None):
    """Получить историю налоговых ставок за период"""
    query = db.query(TaxRate).filter(
        TaxRate.tenant_id == tenant_id
    )
    
    if date_from:
        query = query.filter(
            or_(
                TaxRate.end_date.is_(None),
                TaxRate.end_date >= date_from
            )
        )
    
    if date_to:
        query = query.filter(TaxRate.start_date <= date_to)
    
    return query.order_by(TaxRate.start_date.desc()).all()