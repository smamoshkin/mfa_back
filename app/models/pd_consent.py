from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from .base import Base

# Версия текста согласия на обработку ПД, если фронт не передал свою.
# Текст согласия живёт во фронте: docs/legal/02-consent-pd.md —
# при изменении текста фронт передаёт новую версию в /auth/register.
DEFAULT_CONSENT_VERSION = "1.0"


class PdConsent(Base):
    """Факт согласия на обработку персональных данных (доказательство по 152-ФЗ).

    Пишется при регистрации (галка согласия на фронте блокирует кнопку «Создать
    аккаунт», поэтому успешная регистрация = согласие дано). Хранит, КАКОЙ версии
    текста соглашался пользователь, когда и с какого IP/браузера.
    """

    __tablename__ = "pd_consents"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey('tenants.id'), nullable=False, index=True)

    # Тип согласия: 'pd' — обработка ПД при регистрации; 'marketing' — рассылка (на будущее)
    consent_type = Column(String(50), nullable=False)
    # Версия текста согласия (напр. '1.0') — сверяется с docs/legal во фронте
    text_version = Column(String(50), nullable=False)
    # Момент согласия
    consented_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # IP и User-Agent на момент отправки формы (для доказательства при проверках/спорах)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)

    def __repr__(self):
        return f"<PdConsent(tenant_id={self.tenant_id}, type={self.consent_type}, v{self.text_version})>"
