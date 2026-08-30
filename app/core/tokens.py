"""
Одноразовые токены: подтверждение email ('verify') и сброс пароля ('reset').

Открытый токен существует только в письме пользователя; в БД — sha256-хэш.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.auth_token import AuthToken

# TTL токенов
VERIFY_TTL = timedelta(hours=48)
RESET_TTL = timedelta(minutes=60)
# Минимальная пауза между повторными отправками письма (rate limit)
RESEND_COOLDOWN = timedelta(seconds=60)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_token(db: Session, tenant_id: int, purpose: str) -> str:
    """
    Создаёт токен указанного назначения, возвращает ОТКРЫТОЕ значение
    (оно уйдёт в письмо и нигде больше не сохраняется).
    Предыдущие неиспользованные токены того же назначения гасятся (used_at),
    чтобы актуальным был только последний.
    """
    now = datetime.now(timezone.utc)
    ttl = VERIFY_TTL if purpose == "verify" else RESET_TTL

    db.query(AuthToken).filter(
        AuthToken.tenant_id == tenant_id,
        AuthToken.purpose == purpose,
        AuthToken.used_at.is_(None),
    ).update({"used_at": now})

    token = secrets.token_urlsafe(32)
    db.add(AuthToken(
        tenant_id=tenant_id,
        token_hash=_hash_token(token),
        purpose=purpose,
        expires_at=now + ttl,
    ))
    db.commit()
    return token


def consume_token(db: Session, token: str, purpose: str) -> Optional[int]:
    """
    Проверяет и ПОТРЕБЛЯЕТ токен (одноразовость): находит по хэшу,
    убеждается в назначении, свежести и неиспользованности, ставит used_at.
    Возвращает tenant_id или None.
    """
    db_token = db.query(AuthToken).filter(
        AuthToken.token_hash == _hash_token(token),
        AuthToken.purpose == purpose,
    ).first()

    now = datetime.now(timezone.utc)
    if (
        db_token is None
        or db_token.used_at is not None
        or db_token.expires_at < now
    ):
        return None

    db_token.used_at = now
    db.commit()
    return db_token.tenant_id


def check_token(db: Session, token: str, purpose: str) -> bool:
    """
    Проверяет токен БЕЗ потребления (для валидации ссылки при открытии
    страницы сброса пароля — мгновенная ошибка вместо формы, которая
    упадёт только на сабмите).
    """
    db_token = db.query(AuthToken).filter(
        AuthToken.token_hash == _hash_token(token),
        AuthToken.purpose == purpose,
    ).first()

    now = datetime.now(timezone.utc)
    return bool(
        db_token is not None
        and db_token.used_at is None
        and db_token.expires_at > now
    )


def seconds_since_last_created(db: Session, tenant_id: int, purpose: str) -> Optional[float]:
    """
    Сколько секунд назад создан последний токен назначения purpose.
    Для rate limit повторных отправок. None — токенов не было.
    """
    last = db.query(AuthToken).filter(
        AuthToken.tenant_id == tenant_id,
        AuthToken.purpose == purpose,
    ).order_by(AuthToken.created_at.desc()).first()

    if last is None:
        return None
    if last.created_at.tzinfo is None:
        created = last.created_at.replace(tzinfo=timezone.utc)
    else:
        created = last.created_at
    return (datetime.now(timezone.utc) - created).total_seconds()
