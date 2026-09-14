# Проверка email на "одноразовые" домены (боты-регистрации)
# Источник списка: github.com/disposable-email-domains/disposable-email-domains
# (8833 домена) + актуальные вручную. Список лежит рядом: disposable_domains.txt
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_LIST_PATH = Path(__file__).parent / "disposable_domains.txt"

try:
    with _LIST_PATH.open(encoding="utf-8") as f:
        _DISPOSABLE_DOMAINS = frozenset(
            line.strip().lower() for line in f if line.strip()
        )
except Exception:
    logger.exception("Не удалось загрузить список disposable-доменов")
    _DISPOSABLE_DOMAINS = frozenset()


def is_disposable_email(email: str) -> bool:
    """True, если домен письма входит в блоклист одноразовых сервисов."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain in _DISPOSABLE_DOMAINS
