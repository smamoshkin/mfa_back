# app/routers/tenants.py

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import date
from typing import List

from app.database.database import get_db
from app.schemas.tenant import Tenant, TenantCreate, TenantUpdate
from app.crud import tenant_crud
from app.routers.auth import get_current_tenant
from app.services.wb_token_service import WBTokenDecoder
from app.services.sync_orchestrator import sync_orchestrator
from app.schemas.sync_job import SyncLaunchResponse


router = APIRouter(
    prefix="/tenants",
    tags=["tenants"]
)


# ---------------------------------------------------------------------------
# Текущий аутентифицированный tenant
# ---------------------------------------------------------------------------

@router.get("/me", response_model=Tenant)
def get_current_tenant_info(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Получить информацию о текущем аутентифицированном tenant."""
    return current_tenant


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.post("/", response_model=Tenant, status_code=status.HTTP_201_CREATED)
def create_new_tenant(tenant: TenantCreate, db: Session = Depends(get_db)):
    try:
        return tenant_crud.create_tenant(db=db, tenant=tenant)
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with this email already exists",
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/", response_model=List[Tenant])
def read_tenants(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return tenant_crud.get_tenants(db, skip=skip, limit=limit)


@router.get("/check-email/{email}")
def check_email_availability(email: str, db: Session = Depends(get_db)):
    """Проверить, доступен ли email для регистрации."""
    tenant = tenant_crud.get_tenant_by_email(db, email=email)
    return {
        "email": email,
        "available": tenant is None,
        "exists": tenant is not None,
    }


@router.get("/{tenant_id}", response_model=Tenant)
def get_tenant(
    tenant_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Получить tenant по ID. Только свои данные."""
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    tenant = tenant_crud.get_tenant(db, tenant_id=tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.put("/{tenant_id}", response_model=Tenant)
def update_existing_tenant(
    tenant_id: int,
    tenant: TenantUpdate,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    try:
        db_tenant = tenant_crud.update_tenant(db, tenant_id=tenant_id, tenant=tenant)
        if db_tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return db_tenant
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant with this email already exists",
        )


@router.delete("/{tenant_id}")
def delete_existing_tenant(
    tenant_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    db_tenant = tenant_crud.delete_tenant(db, tenant_id=tenant_id)
    if db_tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"message": "Tenant deleted successfully"}


# ---------------------------------------------------------------------------
# WB API Key — основной endpoint шага 6
# ---------------------------------------------------------------------------

@router.patch("/{tenant_id}/set_wb_key", response_model=SyncLaunchResponse)
def set_wb_api_key(
    tenant_id: int,
    wb_api_key: str = Body(..., embed=True),
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """
    Сохраняет WB API ключ и автоматически запускает initial sync,
    если он ещё не был выполнен.
    """
    # --- Проверка прав ---
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )

    # --- Валидация токена через WBTokenDecoder ---
    expire_at = None
    if wb_api_key:
        token_info = WBTokenDecoder.get_token_info(wb_api_key)
        if not token_info:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid WB API key: failed to decode token",
            )
        if WBTokenDecoder.is_token_expired(wb_api_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WB API key has already expired",
            )
        expire_at = token_info.get("expiry_date")  # datetime | None

    # --- Сохраняем ключ в БД ---
    try:
        updated_tenant = tenant_crud.set_wb_api_key(
            db,
            tenant_id=tenant_id,
            wb_api_key=wb_api_key,
        )
        if not updated_tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Сохраняем дату истечения токена если удалось декодировать
        if expire_at:
            updated_tenant.wb_api_key_expire_at = expire_at
            db.commit()
            db.refresh(updated_tenant)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save WB API key: {str(e)}",
        )

    # --- Запуск initial sync если ещё не выполнялся ---
    sync_job = None
    sync_launched = False

    if wb_api_key:  # Не запускаем если ключ сбрасывается (пустая строка)
        if sync_orchestrator.needs_initial_sync(db, tenant_id):
            sync_job = sync_orchestrator.create_and_launch_initial_sync(
                db=db,
                tenant=updated_tenant,
                triggered_by="user",
            )
            sync_launched = sync_job is not None

    # --- Возвращаем результат ---
    return SyncLaunchResponse(
        sync_launched=sync_launched,
        sync_job_id=sync_job.id if sync_job else None,
        sync_type="initial" if sync_launched else None,
        message=(
            "WB API key saved. Initial data sync started."
            if sync_launched
            else "WB API key saved."
        ),
    )


# ---------------------------------------------------------------------------
# Токен WB — дата истечения
# ---------------------------------------------------------------------------

@router.get("/{tenant_id}/token_expire_date")
def get_token_expiration_date(
    tenant_id: int,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    """Дата истечения WB API токена."""
    if current_tenant.id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    try:
        return tenant_crud.get_token_expiration_date(db, tenant_id=tenant_id)
    except HTTPException:
        raise