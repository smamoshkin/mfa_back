from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
import logging

from app.crud import tenant_crud
from app.database.database import get_db
from app.models.tenant import Tenant
from app.schemas.auth import Token
from app.schemas.tenant import TenantCreate
from app.core.auth import (
    verify_password, get_password_hash, 
    create_access_token, verify_token, ACCESS_TOKEN_EXPIRE_MINUTES
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_tenant(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Tenant:
    tenant_id = verify_token(token)
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant not found or inactive",
        )
    return tenant

@router.post("/register", response_model=Token)
def register(
    tenant_data: TenantCreate,
    db: Session = Depends(get_db)
):
    try:
        logger.info(f"Starting registration for email: {tenant_data.login_email}")
        
        # Создаем tenant через CRUD функцию
        tenant = tenant_crud.create_tenant(db=db, tenant=tenant_data)
        logger.info(f"Tenant created successfully with ID: {tenant.id}")
        
    except HTTPException as e:
        logger.warning(f"HTTPException during registration: {e.detail}")
        raise e
    except Exception as e:
        # Детальное логирование ошибки
        logger.error(f"Unexpected error during registration: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
    
    # Сразу логиним - создаем токен
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(tenant.id)}, expires_delta=access_token_expires
    )
    
    logger.info(f"Registration completed successfully for tenant ID: {tenant.id}")
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    # Ищем tenant по login_email
    # print('username = ', form_data.username)
    # print('password = ', form_data.password)
    tenant = db.query(Tenant).filter(
        Tenant.login_email == form_data.username,
        Tenant.is_active == True
    ).first()
    
    if not tenant or not verify_password(form_data.password, tenant.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    
    # Обновляем last_login
    tenant.last_login = datetime.utcnow()
    db.commit()
    
    # Создаем токен
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(tenant.id)}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}