from pydantic import BaseModel, EmailStr, Field


class TenantLogin(BaseModel):
    login_email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    tenant_id: int | None = None


# ---------------------------------------------------------------------------
# Регистрация / верификация email / сброс пароля
# ---------------------------------------------------------------------------

class RegisterResponse(BaseModel):
    """Регистрация больше НЕ логинит сразу: сначала подтверждение email."""
    message: str
    email: str

class VerifyEmailRequest(BaseModel):
    token: str

class ResendVerificationRequest(BaseModel):
    email: EmailStr

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)

class SimpleMessage(BaseModel):
    message: str
