"""
Отправка транзакционных писем (верификация email, сброс пароля).

Транспорт — SMTP сервера приложения:
  прод:  mail.faapp.ru:587 (docker-mailserver, STARTTLS, авторизация)
  дев:   localhost:1025 (mailpit, без авторизации — docker compose --profile dev)

Реквизиты из .env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
FROM_EMAIL, APP_URL (база ссылок в письмах).

Функции этого модуля БЛОКИРУЮЩИЕ (smtplib) — вызывать только из Celery-задачи
(app/tasks/email_tasks.py), не из HTTP-хендлеров напрямую.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "1025"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "no-reply@faapp.ru")
APP_URL = os.getenv("APP_URL", "http://localhost:5173")


def _send(to: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    # Message-ID и Date ОБЯЗАТЕЛЬНЫ: без них amavis на нашем же mailserver
    # классифицирует письмо как BAD-HEADER и отправляет в карантин,
    # а Postfix по умолчанию их не добавляет
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain=FROM_EMAIL.split("@")[-1])
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        # Mailpit (дев) принимает без STARTTLS и авторизации;
        # прод (docker-mailserver) требует и то, и другое
        try:
            server.starttls()
        except smtplib.SMTPNotSupportedError:
            logger.debug("SMTP server does not support STARTTLS (dev/mailpit?)")
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(FROM_EMAIL, [to], msg.as_string())

    logger.info(f"📧 Email sent to {to}: '{subject}'")


# ---------------------------------------------------------------------------
# Шаблоны писем (простой HTML, без зависимостей)
# ---------------------------------------------------------------------------

def _page(title: str, body_html: str) -> str:
    # Цвета — тема приложения (кобальт #1F2AE1/#1723C4, чернила #193337,
    # мягкий тинт #EEF0FD), см. src/index.css фронта
    return f"""
<!DOCTYPE html>
<html lang="ru">
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:560px;margin:24px auto;background:#ffffff;border-radius:12px;overflow:hidden;">
    <div style="background:linear-gradient(135deg,#1F2AE1,#1723C4);padding:20px 28px;">
      <span style="color:#ffffff;font-size:18px;font-weight:bold;">faapp</span>
    </div>
    <div style="padding:28px;">
      <h2 style="margin:0 0 16px;color:#193337;font-size:18px;">{title}</h2>
      {body_html}
    </div>
    <div style="padding:16px 28px;background:#EEF0FD;color:#A6A5BB;font-size:12px;">
      Это автоматическое письмо, отвечать на него не нужно.
    </div>
  </div>
</body>
</html>
"""


def _button(url: str, label: str) -> str:
    return f"""
    <p style="margin:24px 0;">
      <a href="{url}"
         style="display:inline-block;background:#1F2AE1;color:#ffffff;text-decoration:none;
                padding:12px 28px;border-radius:8px;font-weight:bold;">{label}</a>
    </p>
    <p style="color:#A6A5BB;font-size:13px;">
      Или скопируйте ссылку в браузер:<br>
      <span style="color:#193337;">{url}</span>
    </p>
    """


def send_verification_email(to: str, token: str) -> None:
    url = f"{APP_URL}/verify-email?token={token}"
    _send(
        to,
        "Подтверждение регистрации в faapp",
        _page(
            "Подтвердите ваш email",
            f"""
            <p style="color:#193337;line-height:1.5;">
              Вы зарегистрировались в faapp.
              Чтобы завершить регистрацию и войти в приложение, подтвердите email.
              Ссылка действует 48 часов.
            </p>
            {_button(url, "Подтвердить email")}
            """,
        ),
    )


def send_password_reset_email(to: str, token: str) -> None:
    url = f"{APP_URL}/reset-password?token={token}"
    _send(
        to,
        "Сброс пароля faapp",
        _page(
            "Сброс пароля",
            f"""
            <p style="color:#193337;line-height:1.5;">
              Мы получили запрос на сброс пароля вашего аккаунта.
              Если это были не вы — просто проигнорируйте письмо, пароль не изменится.
              Ссылка действует 60 минут и одноразовая.
            </p>
            {_button(url, "Установить новый пароль")}
            """,
        ),
    )


def send_password_changed_email(to: str) -> None:
    _send(
        to,
        "Пароль faapp изменён",
        _page(
            "Пароль изменён",
            """
            <p style="color:#193337;line-height:1.5;">
              Пароль вашего аккаунта успешно изменён.
              Если это были не вы — срочно восстановите доступ через
              «Забыли пароль?» и обратитесь в поддержку: support@faapp.ru
            </p>
            """,
        ),
    )
