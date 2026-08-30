from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from .base import Base


class AuthToken(Base):
    """
    Одноразовые токены: подтверждение email ('verify') и сброс пароля ('reset').

    В БД хранится только sha256-хэш токена (token_hash). TTL проверяется
    приложением (verify — 48 ч, reset — 60 мин), одноразовость — полем used_at.

    Таблица применяется вручную (db/tables/auth_tokens.sql) — конвенция проекта.
    """
    __tablename__ = "auth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    # 'verify' | 'reset'
    purpose = Column(String(10), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_auth_tokens_tenant_purpose", "tenant_id", "purpose"),
    )
