from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
import logging

from app.crud import tenant_crud
from app.database.database import get_db
from app.models.tenant import Tenant
from app.schemas.auth import (
    Token, RegisterResponse, VerifyEmailRequest,
    ResendVerificationRequest, ForgotPasswordRequest, ResetPasswordRequest,
    SimpleMessage,
)
from app.schemas.tenant import TenantCreate
from app.core.auth import (
    verify_password, get_password_hash,
    create_access_token, verify_token, ACCESS_TOKEN_EXPIRE_MINUTES
)
from app.core import tokens as auth_tokens
from app.tasks.email_tasks import send_email_task


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

@router.post("/register", response_model=RegisterResponse)
def register(
    tenant_data: TenantCreate,
    db: Session = Depends(get_db)
):
    """
    Регистрация: создаёт аккаунт и отправляет письмо со ссылкой подтверждения.
    JWT НЕ выдаётся — вход откроется после подтверждения email
    (POST /auth/verify-email).
    """
    try:
        logger.info(f"Starting registration for email: {tenant_data.login_email}")

        # Создаем tenant через CRUD функцию
        tenant = tenant_crud.create_tenant(db=db, tenant=tenant_data)
        logger.info(f"Tenant created successfully with ID: {tenant.id}")

    except HTTPException as e:
        logger.warning(f"HTTPException during registration: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during registration: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )

    # Токен подтверждения + письмо (фоновая отправка)
    token = auth_tokens.create_token(db, tenant.id, "verify")
    send_email_task.delay("verification", tenant.login_email, token)

    logger.info(f"Registration completed, verification email queued for tenant {tenant.id}")
    return RegisterResponse(
        message="Регистрация выполнена. Проверьте почту — мы отправили письмо со ссылкой подтверждения.",
        email=tenant.login_email,
    )

@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    tenant = db.query(Tenant).filter(
        Tenant.login_email == form_data.username,
        Tenant.is_active == True
    ).first()

    if not tenant or not verify_password(form_data.password, tenant.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Вход закрыт до подтверждения email
    if not tenant.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email is not verified. Please check your inbox for the verification link.",
            # фронт по этому коду показывает блок с повторной отправкой письма
            headers={"X-Error-Code": "email_unverified"},
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


# ---------------------------------------------------------------------------
# Верификация email / сброс пароля
# ---------------------------------------------------------------------------

@router.post("/verify-email", response_model=Token)
def verify_email(
    body: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    """
    Подтверждение email по одноразовому токену из письма.
    Сразу логинит (возвращает JWT).
    """
    tenant_id = auth_tokens.consume_token(db, body.token, "verify")
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка недействительна или устарела. Запросите письмо заново.",
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.email_verified = True
    tenant.last_login = datetime.utcnow()
    db.commit()

    access_token = create_access_token(
        data={"sub": str(tenant.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    logger.info(f"✅ Email verified for tenant {tenant.id}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/resend-verification", response_model=SimpleMessage)
def resend_verification(
    body: ResendVerificationRequest,
    db: Session = Depends(get_db),
):
    """
    Повторная отправка письма подтверждения. Всегда 200 (не раскрываем
    существование email). Rate limit — 60 секунд между письмами.
    """
    tenant = db.query(Tenant).filter(Tenant.login_email == body.email).first()

    if tenant and not tenant.email_verified:
        since = auth_tokens.seconds_since_last_created(db, tenant.id, "verify")
        if since is not None and since < auth_tokens.RESEND_COOLDOWN.total_seconds():
            return SimpleMessage(
                message="Письмо уже отправлено недавно. Проверьте почту или попробуйте через минуту."
            )
        token = auth_tokens.create_token(db, tenant.id, "verify")
        send_email_task.delay("verification", tenant.login_email, token)

    return SimpleMessage(message="Если аккаунт существует, письмо отправлено.")


@router.post("/forgot-password", response_model=SimpleMessage)
def forgot_password(
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Запрос сброса пароля. ВСЕГДА 200 — не раскрываем существование email.
    Письмо со ссылкой уходит только существующему верифицированному аккаунту.
    """
    tenant = db.query(Tenant).filter(Tenant.login_email == body.email).first()

    if tenant and tenant.email_verified:
        since = auth_tokens.seconds_since_last_created(db, tenant.id, "reset")
        if since is not None and since < auth_tokens.RESEND_COOLDOWN.total_seconds():
            return SimpleMessage(message="Если аккаунт существует, письмо отправлено.")
        token = auth_tokens.create_token(db, tenant.id, "reset")
        send_email_task.delay("password_reset", tenant.login_email, token)

    return SimpleMessage(message="Если аккаунт существует, письмо отправлено.")


@router.post("/validate-reset-token")
def validate_reset_token(
    body: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    """
    Проверка reset-токена БЕЗ потребления — чтобы страница смены пароля
    сразу показывала ошибку для использованной/устаревшей ссылки,
    а не форму, которая упадёт только на сабмите.
    """
    return {"valid": auth_tokens.check_token(db, body.token, "reset")}


@router.post("/reset-password", response_model=SimpleMessage)
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """
    Установка нового пароля по одноразовому токену из письма.
    """
    tenant_id = auth_tokens.consume_token(db, body.token, "reset")
    if tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка недействительна, устарела или уже была использована.",
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.hashed_password = get_password_hash(body.new_password)
    db.commit()

    # Уведомление о смене пароля (best practice)
    send_email_task.delay("password_changed", tenant.login_email)

    logger.info(f"🔑 Password reset for tenant {tenant.id}")
    return SimpleMessage(message="Пароль изменён. Теперь войдите с новым паролем.")