from pydantic import BaseModel, EmailStr


class TenantLogin(BaseModel):
    login_email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    tenant_id: int | None = None