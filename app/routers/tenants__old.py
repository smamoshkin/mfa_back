from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import date
from typing import List

from app.database.database import get_db
from app.schemas.tenant import Tenant, TenantCreate, TenantUpdate
from app.crud import tenant_crud
from app.routers.auth import get_current_tenant
from app.tasks.sync_tasks__old import sync_tenant_wb_data
from app.services.wb_token_service import WBTokenDecoder


# Создаем роутер с префиксом и тегами для документации
router = APIRouter(
    prefix="/tenants",  # Все эндпоинты будут начинаться с /tenants
    tags=["tenants"]    # Группировка в Swagger UI
)

# 👇 ЗАЩИЩЕННЫЙ эндпоинт - требует аутентификации
@router.get("/me", response_model=Tenant)
def get_current_tenant_info(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получить информацию о текущем аутентифицированном tenant"""
    return current_tenant

# 👇 ЗАЩИЩЕННЫЙ эндпоинт - требует аутентификации
@router.get("/{tenant_id}", response_model=Tenant)
def get_tenant(
    tenant_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),  # 👈 требует аутентификации
    db: Session = Depends(get_db)
):
    """Получить tenant по ID (только для аутентифицированных пользователей)"""
    # Проверяем, что пользователь запрашивает свои данные
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant

@router.post("/", response_model=Tenant, status_code=status.HTTP_201_CREATED)
def create_new_tenant(tenant: TenantCreate, db: Session = Depends(get_db)):
    try:
        return tenant_crud.create_tenant(db=db, tenant=tenant)
    except HTTPException:
        # Перебрасываем наши кастомные HTTPException
        raise
    except IntegrityError as e:
        # Ловим ошибки уникальности от БД
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with this email already exists"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/", response_model=List[Tenant])
def read_tenants(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    tenants = tenant_crud.get_tenants(db, skip=skip, limit=limit)
    return tenants

@router.get("/{tenant_id}", response_model=Tenant)
def read_tenant(tenant_id: int, db: Session = Depends(get_db)):
    db_tenant = tenant_crud.get_tenant(db, tenant_id=tenant_id)
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return db_tenant

@router.put("/{tenant_id}", response_model=Tenant)
def update_existing_tenant(tenant_id: int, tenant: TenantUpdate, db: Session = Depends(get_db)):
    try:
        db_tenant = tenant_crud.update_tenant(db, tenant_id=tenant_id, tenant=tenant)
        if db_tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return db_tenant
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with this email already exists"
        )

@router.delete("/{tenant_id}")
def delete_existing_tenant(tenant_id: int, db: Session = Depends(get_db)):
    db_tenant = tenant_crud.delete_tenant(db, tenant_id=tenant_id)
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"message": "Tenant deleted successfully"}

@router.get("/check-email/{email}")
def check_email_availability(email: str, db: Session = Depends(get_db)):
    """Проверить, доступен ли email для регистрации"""
    tenant = tenant_crud.get_tenant_by_email(db, email=email)
    return {
        "email": email,
        "available": tenant is None,
        "exists": tenant is not None
    }

@router.patch("/{tenant_id}/set_wb_key")
def set_wb_api_key(
    tenant_id: int, 
    wb_api_key: str, 
    current_tenant: Tenant = Depends(get_current_tenant),  # 👈 добавляем аутентификацию
    db: Session = Depends(get_db)
):
    # Проверяем, что пользователь обновляет свои данные
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    try:
        # Обновляем ключ в БД
        updated_tenant = tenant_crud.set_wb_api_key(db, tenant_id=tenant_id, wb_api_key=wb_api_key)
        
        # 👇 ЗАПУСКАЕМ АВТОМАТИЧЕСКУЮ СИНХРОНИЗАЦИЮ
        # if updated_tenant and wb_api_key:  # Если ключ не пустой
        #     task = sync_tenant_wb_data.delay(
        #         tenant_id=tenant_id,
        #         date_from="2023-01-01",  # История с 2023 года
        #         date_to=date.today().isoformat()  # По сегодня
        #     )
        #     print(f"🚀 Started automatic sync task {task.id} for tenant {tenant_id}")
        
        return updated_tenant
    except HTTPException:
        raise


@router.get("/{tenant_id}/token_expire_date")
def get_token_expiration_date(
    tenant_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    #Проверка, что пользователь проверяет свой токен
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permission"
        )
    
    try:
        return tenant_crud.get_token_expiration_date(db, tenant_id=tenant_id)
    
    except HTTPException:
        raise

         