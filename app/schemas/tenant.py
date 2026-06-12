from pydantic import BaseModel, ConfigDict, EmailStr
from datetime import datetime
from typing import Optional

# Базовые свойства, общие для всех схем
class TenantBase(BaseModel):
    name: str
    login_email: str  
    wb_api_key: Optional[str] = None
    ozon_api_key: Optional[str] = None
    is_active: bool = True

# Схема для создания нового тенанта (не включает id и timestamps)
class TenantCreate(TenantBase):
    name: str
    login_email: EmailStr
    password: str  

# Схема для обновления (все поля опциональны)
class TenantUpdate(BaseModel):
    name: Optional[str] = None
    login_email: Optional[str] = None
    wb_api_key: Optional[str] = None
    ozon_api_key: Optional[str] = None
    is_active: Optional[bool] = None
    wb_api_key_expire_at: Optional[datetime] = None

# Схема, возвращаемая в ответе API (включает id и timestamps)
class Tenant(TenantBase):
    model_config = ConfigDict(from_attributes=True)  # Работа с ORM (ранее orm_mode = True)

    id: int
    login_email: str
    email_verified: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    wb_api_key_expire_at: Optional[datetime] = None