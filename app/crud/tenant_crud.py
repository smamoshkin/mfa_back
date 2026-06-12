from sqlalchemy.orm import Session
from app.models.tenant import Tenant
from app.schemas.tenant import TenantCreate, TenantUpdate
from fastapi import HTTPException, status
from datetime import datetime
from app.core.auth import get_password_hash
from app.services.wb_token_service import WBTokenDecoder
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def get_tenant_by_email(db: Session, email: str):
    """Получить тенанта по email"""
    return db.query(Tenant).filter(Tenant.login_email == email).first()

def get_tenant(db: Session, tenant_id: int):
    # Возвращает тенанта по ID или None
    return db.query(Tenant).filter(Tenant.id == tenant_id).first()

def get_tenants(db: Session, skip: int = 0, limit: int = 100):
    # Возвращает список тенантов с пагинацией
    return db.query(Tenant).offset(skip).limit(limit).all()

def create_tenant(db: Session, tenant: TenantCreate):
    # Проверяем, существует ли уже тенант с таким email
    db_tenant = get_tenant_by_email(db, email=tenant.login_email)
    if db_tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with this email already exists"
        )
    
    # Создаем словарь данных, исключая пароль
    tenant_data = tenant.model_dump(exclude={'password'})
    
    # Добавляем хешированный пароль и дату создания
    tenant_data['hashed_password'] = get_password_hash(tenant.password)
    tenant_data['created_at'] = datetime.utcnow()  # 👈 Явно устанавливаем дату
    
    # Создаем нового тенанта в БД
    db_tenant = Tenant(**tenant_data)
    db.add(db_tenant)
    db.commit()
    db.refresh(db_tenant) # Обновляем объект данными из БД (чтобы получить id и timestamps)
    return db_tenant

def update_tenant(db: Session, tenant_id: int, tenant: TenantUpdate):
    # Обновляет данные тенанта
    db_tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not db_tenant:
        return None
    
    # Если обновляется email, проверяем его уникальность
    if tenant.login_email and tenant.login_email != db_tenant.login_email:
        existing_tenant = get_tenant_by_email(db, email=tenant.login_email)
        if existing_tenant:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tenant with this email already exists"
            )
    
    # Обновляем только переданные поля
    update_data = tenant.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_tenant, field, value)
    
    db.commit()
    db.refresh(db_tenant)
    return db_tenant

def delete_tenant(db: Session, tenant_id: int):
    # Удаляет тенанта
    db_tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not db_tenant:
        return None
    db.delete(db_tenant)
    db.commit()
    return db_tenant

def set_wb_api_key(db: Session, tenant_id: int, wb_api_key: str):
    """Установить API ключ для WB с проверкой и сохранением даты истечения"""
    # Находим tenant
    db_tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not db_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with tenant_id={tenant_id} not found"
        )
    
    # Валидируем токен
    token_info = WBTokenDecoder.get_token_info(wb_api_key)
    
    if not token_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный формат токена Wildberries"
        )
    
    # Проверяем, не истек ли токен
    if WBTokenDecoder.is_token_expired(wb_api_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Токен Wildberries истек. Пожалуйста, обновите токен"
        )
    
    # Проверяем наличие необходимых прав
    if "Аналитика" not in token_info['permissions']:
        logger.warning(f"Токен tenant_id={tenant_id} не имеет прав на аналитику")
        # Можно сделать предупреждение, но не блокировать сохранение
        # raise HTTPException(...)
    
    # Обновляем поля в базе данных
    db_tenant.wb_api_key = wb_api_key
    db_tenant.wb_api_key_expire_at = token_info['expiry_date']
    db_tenant.wb_api_key_last_checked = datetime.utcnow()
    db_tenant.wb_seller_id = token_info['seller_id']
    db_tenant.updated_at = datetime.utcnow()
    
    # Логируем информацию о токене
    logger.info(
        f"Токен для tenant_id={tenant_id} сохранен. "
        f"Тип: {token_info['token_type']}, "
        f"Истекает: {token_info['expiry_date']}, "
        f"Права: {', '.join(token_info['permissions'])}"
    )
    
    db.commit()
    db.refresh(db_tenant)
    return db_tenant

def check_wb_token_expiry(db: Session, tenant_id: int) -> Dict[str, Any]:
    """
    Проверить срок действия токена Wildberries
    
    Returns:
        Информация о статусе токена
    """
    db_tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not db_tenant or not db_tenant.wb_api_key:
        return {
            'has_token': False,
            'message': 'Токен не установлен'
        }
    
    token_info = WBTokenDecoder.get_token_info(db_tenant.wb_api_key)
    
    if not token_info:
        return {
            'has_token': True,
            'is_valid': False,
            'message': 'Токен невалиден'
        }
    
    # Проверяем срок действия
    days_left = WBTokenDecoder.get_days_to_expiry(db_tenant.wb_api_key)
    
    status_info = {
        'has_token': True,
        'is_valid': True,
        'seller_id': token_info['seller_id'],
        'token_type': token_info['token_type'],
        'expiry_date': token_info['expiry_date'],
        'days_left': days_left,
        'permissions': token_info['permissions'],
        'is_test': token_info['is_test']
    }
    
    # Добавляем предупреждения
    warnings = []
    
    if days_left is not None:
        if days_left <= 0:
            status_info['is_valid'] = False
            warnings.append('Токен истек')
        elif days_left <= 7:
            warnings.append(f'Токен истекает через {days_left} дней')
        
        # Обновляем дату последней проверки
        db_tenant.wb_api_key_last_checked = datetime.utcnow()
        db.commit()
    
    if "Аналитика" not in token_info['permissions']:
        warnings.append('Токен не имеет прав на аналитику')
    
    if token_info['is_test']:
        warnings.append('Это тестовый токен')
    
    status_info['warnings'] = warnings
    
    return status_info


def refresh_wb_token_expiry(db: Session, tenant_id: int) -> bool:
    """
    Обновить информацию о сроке действия токена в БД
    
    Returns:
        True если успешно, False если токен невалиден
    """
    db_tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not db_tenant or not db_tenant.wb_api_key:
        return False
    
    token_info = WBTokenDecoder.get_token_info(db_tenant.wb_api_key)
    if not token_info:
        return False
    
    # Обновляем поля в базе данных
    db_tenant.wb_api_key_expire_at = token_info['expiry_date']
    db_tenant.wb_api_key_last_checked = datetime.utcnow()
    db_tenant.updated_at = datetime.utcnow()
    
    db.commit()
    return True

def get_token_expiration_date(db: Session, tenant_id: int) -> str:
    """
    Получить дату истечения токена пользователя
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return tenant.wb_api_key_expire_at
