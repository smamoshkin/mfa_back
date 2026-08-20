# Процесс поставки (CI/CD)

Схема: push тега `v*` → GitHub Actions собирает образ → пушит в GHCR → деплой по SSH на сервер.

## Структура

- **mfa_back** (этот репозиторий):
  - `Dockerfile` — multi-stage сборка бэка (gunicorn, без компиляторов в финальном образе)
  - `entrypoint.sh` — запуск gunicorn с uvicorn-workers
  - `docker-compose.prod.yml` — продовый compose (образы из GHCR, ничего не собирается на сервере)
  - `nginx/nginx.conf` — конфиг внешних nginx-ворот (эталон; на сервере лежит в `./nginx/nginx.conf`)
  - `.github/workflows/deploy.yml` — сборка + деплой `backend`, `celery_worker`, `celery_beat`
- **mfa_front**:
  - `Dockerfile` — сборка Vite + nginx-статика (API URL задаётся build-arg `VITE_API_BASE_URL=/api/`)
  - `nginx.conf` — конфиг nginx внутри фронтенд-образа (SPA-fallback)
  - `.github/workflows/deploy.yml` — сборка + деплой `frontend`

На сервере в `/home/market_app/marketfinanceapp` хранятся только:
`docker-compose.yml` (= `docker-compose.prod.yml`), `.env`, `nginx/nginx.conf`, volumes (postgres_data, redis_data, celerybeat_data, backup, logs, ssl).

## Релиз

```bash
# в нужном репозитории
git tag v1.2.0
git push origin v1.2.0
```
Дальше всё автоматически: Actions → сборка → GHCR → SSH-деплой.
Прогресс: вкладка Actions в репозитории.

## Откат

```bash
# на сервере
cd /home/market_app/marketfinanceapp
BACKEND_TAG=v1.1.0 docker compose up -d backend celery_worker celery_beat   # или FRONTEND_TAG для фронта
```

## Разовая инициализация (уже сделано — для справки)

1. Deploy-ключ: `ssh-keygen -t ed25519 -f ~/.ssh/mfa_deploy -N ""`,
   pubkey → `~/.ssh/authorized_keys` на сервере,
   приватный ключ → секрет `SSH_PRIVATE_KEY` в обоих репозиториях,
   плюс `SSH_HOST`, `SSH_USER` (и `SSH_PORT`, если не 22).
2. На сервере: `docker login ghcr.io` (GitHub PAT со скоупом `read:packages`).
3. Заменить `docker-compose.yml` на сервере содержимым `docker-compose.prod.yml`.
4. `environment: production` в workflow — при желании настроить approvers в Settings → Environments.

## Замечания

- Postgres/Redis — официальные образы, не пересобираются, данные в volumes.
- Фронтенд: `npm run build` = `vite build` (проверка типов отключена — 73 ошибки TS в коде, почистить отдельной задачей; проверять руками через `npm run typecheck`).
- Миграций Alembic нет (таблицы создаёт `create_all()` при старте) — шаг миграций в деплое появится, когда появятся миграции.
