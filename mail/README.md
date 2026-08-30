# Собственный почтовый сервер (docker-mailserver)

Сервис `mailserver` в docker-compose: SMTP (отправка писем приложения + приём
входящих) и IMAP (ящик `support@faapp.ru`). Настройка — один раз, по шагам ниже.

---

## 1. DNS-записи (у регистратора домена faapp.ru)

| Запись | Имя | Значение | Примечание |
|---|---|---|---|
| A | `mail.faapp.ru` | `188.127.240.202` | |
| MX | `@` (faapp.ru) | `mail.faapp.ru.` приоритет 10 | приём входящих писем |
| TXT (SPF) | `@` | `v=spf1 mx ~all` | одна SPF-запись на домен! |
| TXT (DMARC) | `_dmarc` | `v=DMARC1; p=none; rua=mailto:postmaster@faapp.ru` | p=none — мониторинг, не блокируем |
| TXT (DKIM) | `mail._domainkey` | (сгенерируется на шаге 4) | |

**PTR у хостера (SmartApe)**: в панели управления VPS (или тикетом) установить
обратную DNS для `188.127.240.202` → `mail.faapp.ru`. Без этого Gmail/Яндекс
кладут письма в спам.

⚠️ Если у `faapp.ru` уже есть TXT-запись с `v=spf1` — SPF может быть только
один, объедините значения.

---

## 2. TLS-сертификат для mail.faapp.ru (Let's Encrypt)

Всё в докере: ACME-челлендж обслуживает nginx-контейнер (webroot
`/var/www/certbot` = `./ssl/webroot`), certbot запускается разовым контейнером,
сертификаты живут в `./ssl/letsencrypt` (рядом с существующим `faapp.ru`).

1. В `nginx/nginx.conf` уже добавлен server-block `mail.faapp.ru:80` только
   для ACME-челленджа (см. репо).

2. Применить конфиг nginx:
```bash
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
```

3. Выпустить сертификат разовым контейнером certbot (аккаунт LE уже есть
   в ./ssl/letsencrypt/accounts — переиспользуется):
```bash
cd ~/marketfinanceapp
docker run --rm \
  -v $(pwd)/ssl/letsencrypt:/etc/letsencrypt \
  -v $(pwd)/ssl/webroot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot -d mail.faapp.ru
```

4. Проверка:
```bash
sudo openssl x509 -in ssl/letsencrypt/live/mail.faapp.ru/fullchain.pem -noout -subject -dates
# subject=CN = mail.faapp.ru + сроки действия
```

5. Продление: вместе с существующим сертификатом faapp.ru — тем же способом,
   которым продлевается он, плюс `docker compose restart mailserver` после
   обновления (mailserver читает сертификат только при старте).

---

## 3. Первый запуск и ящики

```bash
docker compose up -d mailserver

# Ящик-отправитель для приложения (пароль = SMTP_PASSWORD из .env)
docker compose exec mailserver setup email add no-reply@faapp.ru '<ПАРОЛЬ_1>'

# Ящик для обращений пользователей (IMAP)
docker compose exec mailserver setup email add support@faapp.ru '<ПАРОЛЬ_2>'
```

В `.env` прода:
```
SMTP_HOST=mail.faapp.ru
SMTP_PORT=587
SMTP_USER=no-reply@faapp.ru
SMTP_PASSWORD=<ПАРОЛЬ_1>
FROM_EMAIL=no-reply@faapp.ru
APP_URL=https://faapp.ru
```

## 4. DKIM-ключ → DNS

```bash
docker compose exec mailserver setup config dkim
```
Команда выведет TXT-запись для `mail._domainkey.faapp.ru` — добавьте её у
регистратора (шаг 1, последняя строка таблицы).

## 5. Проверка

1. Исходящее: из приложения (или `swaks`) отправить письмо на свой личный
   ящик → проверить, что дошло во «Входящие» (не в спам), в заголовках есть
   `DKIM-Signature` и `SPF: pass`.
2. Входящее: написать письмо на `support@faapp.ru` с личного ящика →
   забрать по IMAP (`mail.faapp.ru:993`, логин `support@faapp.ru`).
3. Диагностика: `docker compose logs -f mailserver`.

## 6. Эксплуатация

- Антиспам входящих — Rspamd (уже включён). При ложных срабатываниях: логи
  `docker compose logs mailserver`, белый список отправителей — через файл
  `./mail/docker-mailserver/config/postfix-accounts.cf` см. документацию
  docker-mailserver (раздел Rspamd / whitelisting).
- fail2ban включён — автоматическая блокировка перебора паролей.
- Обновление: `docker compose pull mailserver && docker compose up -d mailserver`.

---

## Дев-среда: Mailpit

Локально поднимается контейнер-перехватчик писем:
```bash
docker compose --profile dev up -d mailpit
```
- SMTP: `localhost:1025` (без авторизации — в дев-.env: `SMTP_HOST=localhost`,
  `SMTP_PORT=1025`, пароль любой);
- веб-интерфейс всех пойманных писем: `http://localhost:8025`.
На проде не поднимается (compose-profile `dev`).
