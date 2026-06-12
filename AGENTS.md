# MarketFinanceApp — Руководство для AI-агентов

## О проекте

**MarketFinanceApp** — это бэкенд-приложение (API) для автоматизации финансовой аналитики продавцов на маркетплейсах. На данный момент реализована интеграция с **Wildberries**; заложена основа для будущей интеграции с **Ozon**.

Приложение предназначено для:
- Загрузки и хранения данных о продажах из API Wildberries
- Расчёта рентабельности и прибыльности товаров
- Генерации Excel-отчётов с формулами
- Многопользовательской (multi-tenant) работы — каждый пользователь видит только свои данные

---

## Технологический стек

| Компонент | Технология | Версия |
|-----------|------------|--------|
| Веб-фреймворк | FastAPI | 0.135.1 |
| ASGI-сервер | Uvicorn | 0.24.0 |
| ORM | SQLAlchemy | 2.0.23 |
| Валидация схем | Pydantic | 2.5.0 |
| База данных | PostgreSQL | 15 (Alpine) |
| Драйвер БД | psycopg2-binary | 2.9.9 |
| Миграции | Alembic | 1.12.1 |
| Очередь задач | Celery | 5.5.3 |
| Брокер задач | Redis | 7 (Alpine) |
| Мониторинг задач | Flower | 2.0.1 |
| Асинхронный HTTP | aiohttp | 3.11.11 |
| Обработка данных | Pandas | 3.0.1 |
| Генерация Excel | openpyxl | 3.1.5 |
| Аутентификация | PyJWT, python-jose, passlib | — |
| Язык | Python | 3.11 |

---

## Архитектура проекта

```
marketfinanceapp/
├── app/                              # Основной пакет приложения
│   ├── main.py                       # Точка входа FastAPI, CORS, регистрация роутеров
│   ├── celery_app.py                 # Конфигурация Celery-воркера
│   ├── core/
│   │   └── auth.py                   # JWT: хеширование паролей, создание/проверка токенов
│   ├── database/
│   │   └── database.py               # SQLAlchemy engine + session factory
│   ├── models/                       # SQLAlchemy ORM модели
│   │   ├── tenant.py                 # Пользователи (тенанты)
│   │   ├── product.py                # Товары
│   │   ├── product_cost.py           # Себестоимость товаров
│   │   ├── supplier_report.py        # Отчёты поставщика (данные из WB)
│   │   ├── tax_rate.py               # Налоговые ставки
│   │   └── analytics_views.py        # Ссылки на DB views для аналитики
│   ├── schemas/                      # Pydantic схемы запросов/ответов
│   ├── crud/                         # Слой доступа к данным (CRUD операции)
│   ├── routers/                      # API эндпоинты FastAPI
│   │   ├── auth.py                   # /auth — регистрация и вход
│   │   ├── tenants.py                # /tenants — управление тенантами
│   │   ├── products.py               # /products — товары
│   │   ├── product_costs.py          # /product-costs — себестоимость
│   │   ├── supplier_reports.py       # /supplier-reports — отчёты
│   │   ├── sync.py                   # /sync — синхронизация с WB
│   │   ├── celery_tasks.py           # /tasks — управление Celery задачами
│   │   ├── periodic_sync.py          # /periodic-sync — периодическая синхронизация
│   │   ├── analytics.py              # /analytics — аналитика и экспорт
│   │   ├── dashboard.py              # /dashboard — данные для дашборда
│   │   ├── tax_rates.py              # /tax-rates — налоговые ставки
│   │   └── debug.py                  # /debug — отладочные эндпоинты (закомментирован)
│   ├── services/                     # Бизнес-логика
│   │   ├── wb_api_client.py          # Асинхронный клиент к API Wildberries
│   │   ├── sync_service.py           # Оркестрация синхронизации с WB
│   │   ├── report_mapper.py          # Трансформация данных WB API в модели
│   │   ├── product_sync_service.py   # Синхронизация карточек товаров
│   │   ├── analytics_service.py      # Расчёт рентабельности и прибыльности
│   │   ├── report_generator.py       # Генерация Excel-отчётов
│   │   └── wb_token_service.py       # Декодирование JWT-токенов WB
│   └── tasks/                        # Celery фоновые задачи
│       ├── sync_tasks.py             # Задача синхронизации тенанта
│       └── periodic_sync.py          # Еженедельная синхронизация всех тенантов
├── alembic/                          # Настройки миграций (версии отсутствуют)
├── db/                               # DDL скрипки БД
│   ├── tables/                       # Создание таблиц (tenants, products, product_costs, supplier_reports, tax_rates)
│   └── views/                        # Создание представлений (supplier_reports_aggregated_v, product_margins_month_v)
├── docker-compose.yml                # PostgreSQL + Redis + backend
├── Dockerfile                        # Образ на базе python:3.11-slim
├── .env                              # Переменные окружения (DATABASE_URL, REDIS_URL)
└── new_requirements.txt              # Зависимости проекта
```

---

## Слои архитектуры

Приложение следует классической многослойной архитектуре:

1. **Routers (Маршрутизаторы)** — HTTP эндпоинты, валидация входных данных через Pydantic схемы
2. **CRUD** — операции с базой данных через SQLAlchemy ORM
3. **Services (Сервисы)** — бизнес-логика: вызовы внешних API, расчёты, трансформации данных
4. **Models (Модели)** — SQLAlchemy ORM модели таблиц БД
5. **Schemas (Схемы)** — Pydantic модели для валидации запросов/ответов

---

## Модели данных

### Tenant (`tenants`) — Пользователи/тенанты
- `id`, `name`, `login_email` (unique), `hashed_password`
- `wb_api_key`, `wb_api_key_expire_at` (дата истечения API ключа)
- `ozon_api_key` (на будущее)
- `is_active`, `email_verified` (default: false), `created_at`, `updated_at`, `last_login`
- Индексы: `ix_tenants_id`, `ix_tenants_login_email` (UNIQUE)
- Связи: `products`, `supplier_reports`, `tax_rates`

### Product (`products`) — Товары
- `id`, `tenant_id` (FK → tenants), `sku`, `marketplace_sku`
- `foto`, `barcode`, `name`, `description` (text), `category`
- `is_active`, `created_at` (default: CURRENT_TIMESTAMP), `updated_at` (default: CURRENT_TIMESTAMP)
- Unique constraint: `(tenant_id, sku)`
- Индекс: `ix_products_id`

### ProductCost (`product_costs`) — Себестоимость (историческая)
- `id`, `product_id` (FK → products), `cost` (DECIMAL 10,2)
- `start_date`, `end_date` (nullable = текущая), `created_at` (default: CURRENT_TIMESTAMP), `created_by`

### SupplierReport (`supplier_reports`) — Данные из WB
- `id` (bigserial), `tenant_id` (FK)
- `realizationreport_id`, `rrd_id` (int8)
- `date_from`, `date_to`, `sale_dt`, `sku`
- `doc_type_name` (varchar 1000), `supplier_oper_name` (varchar 1000), `quantity`
- `retail_amount`, `amount_for_pay`, `retail_price`
- `storage_fee`, `bonus_type_name` (text), `deduction`, `delivery_rub`, `penalty`, `acceptance`
- `raw_data` (JSON), `extracted_fields` (JSON), `created_at`

### TaxRate (`tax_rates`) — Налоговые ставки (исторические)
- `id`, `tenant_id` (FK → tenants, CASCADE DELETE), `tax_rate` (DECIMAL 5,2)
- `start_date`, `end_date` (nullable), `created_at` (default: CURRENT_TIMESTAMP), `created_by`
- CHECK: `tax_rate` от 0 до 100; `end_date IS NULL OR end_date > start_date`
- UNIQUE: `(tenant_id, start_date, end_date)`
- Индексы: `ix_tax_rates_id`, `ix_tax_rates_tenant_id`, `ix_tax_rates_date_range`

### Database Views (представления в БД)
Полные DDL находятся в папке `db/views/`.

- **`supplier_reports_aggregated_v`** — агрегированные продажи по периодам (день/неделя/месяц/квартал/год). Присоединяет `tax_rates` и `product_costs` по датам, рассчитывает: количество продаж/возвратов, выручку, выплаты продавцу, налог (ставка по дате), себестоимость, хранение, удержания (разделяет обычные и «джем»), доставку, штрафы, приёмку, маржу.
- **`product_margins_month_v`** — ежемесячная маржинальность товаров на основе `supplier_reports_aggregated_v`. Группирует по `(tenant_id, period_month, product_name, sku)`, рассчитывает: маржу %, маржу на единицу, логистику на единицу и другие показатели.

> **Важно:** Представления создаются НЕ через SQLAlchemy, а напрямую в PostgreSQL. Alembic миграции не настроены — таблицы создаются через `metadata.create_all()` при старте приложения.

---

## API эндпоинты

### Аутентификация (`/auth`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/auth/register` | Регистрация нового тенанта (возвращает JWT) |
| POST | `/auth/login` | Вход по email/паролю (OAuth2PasswordBearer) |

### Тенанты (`/tenants`)
| Метод | Путь | Описание | Auth |
|-------|------|----------|------|
| GET | `/tenants/me` | Текущий авторизованный тенант | Да |
| GET | `/tenants/{id}` | Получить тенант по ID | Да + проверка владения |
| POST | `/tenants/` | Создать тенант | Нет |
| GET | `/tenants/` | Список тенантов (пагинация) | Нет |
| PUT | `/tenants/{id}` | Обновить тенант | Нет |
| DELETE | `/tenants/{id}` | Удалить тенант | Нет |
| GET | `/tenants/check-email/{email}` | Проверить доступность email | Нет |
| PATCH | `/tenants/{id}/set_wb_key` | Установить WB API ключ | Да + проверка владения |
| GET | `/tenants/{id}/token_expire_date` | Дата истечения токена | Да + проверка владения |

### Товары (`/products`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/products/` | Создать товар (tenant_id ставится автоматически) |
| GET | `/products/` | Список товаров текущего тенанта |
| GET | `/products/{id}` | Получить товар по ID |
| PUT | `/products/{id}` | Обновить товар |
| DELETE | `/products/{id}` | Удалить товар |
| GET | `/products/sku/{sku}` | Найти по SKU |
| GET | `/products/marketplace-sku/{sku}` | Найти по marketplace SKU |

### Себестоимость (`/product-costs`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/product-costs/` | Создать запись себестоимости |
| GET | `/product-costs/product/{id}` | Все записи себестоимости товара |
| GET | `/product-costs/product/{id}/current` | Текущая активная себестоимость |
| GET | `/product-costs/product/{id}/date/{date}` | Себестоимость на дату |
| GET | `/product-costs/{id}` | Получить запись по ID |
| PUT | `/product-costs/{id}` | Обновить запись |
| DELETE | `/product-costs/{id}` | Удалить запись |
| PATCH | `/product-costs/{id}/close` | Закрыть период (установить end_date) |

### Отчёты поставщика (`/supplier-reports`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/supplier-reports/bulk/` | Массовое создание записей |
| GET | `/supplier-reports/` | Список отчётов текущего тенанта |
| GET | `/supplier-reports/period/` | Фильтр по периоду дат |
| GET | `/supplier-reports/{id}` | Получить отчёт по ID |
| POST | `/supplier-reports/import/wb/` | Импорт данных из WB |

### Синхронизация (`/sync`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/sync/wb/{tenant_id}` | Запустить синхронизацию WB (Celery) |
| POST | `/sync/wb/{tenant_id}/background` | Фоновая синхронизация |
| GET | `/sync/task/{task_id}/status` | Статус Celery задачи |

### Задачи Celery (`/tasks`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/tasks/sync/wb/{tenant_id}` | Запустить задачу синхронизации |
| GET | `/tasks/status/{task_id}` | Получить статус задачи |

### Периодическая синхронизация (`/periodic-sync`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/periodic-sync/run-weekly-sync` | Запустить еженедельную синхронизацию всех тенантов |
| GET | `/periodic-sync/task-status/{task_id}` | Статус задачи синхронизации |

### Аналитика (`/analytics`)
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/analytics/rentability` | Отчёт рентабельности/прибыльности |
| GET | `/analytics/financial-overview` | Финансовый обзор (заглушка) |
| POST | `/analytics/export/excel` | Экспорт аналитики в Excel с формулами |

### Дашборд (`/dashboard`)
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/dashboard` | Полные данные дашборда (метрики, графики, топ товаров, активность) |
| GET | `/dashboard/metrics` | Только ключевые метрики |
| GET | `/dashboard/sales-chart` | Данные графика продаж (7/30/90 дней) |
| GET | `/dashboard/top-products` | Топ продаваемых товаров |
| GET | `/dashboard/recent-activity` | Последняя активность |
| POST | `/dashboard/sync` | Запустить синхронизацию из дашборда |

### Налоговые ставки (`/tax-rates`)
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/tax-rates/` | Создать налоговую ставку |
| GET | `/tax-rates/` | Список всех ставок (тенант) |
| GET | `/tax-rates/current` | Текущая активная ставка |
| GET | `/tax-rates/date/{date}` | Ставка на дату |
| GET | `/tax-rates/history` | История ставок |
| GET | `/tax-rates/{id}` | Получить ставку по ID |
| PUT | `/tax-rates/{id}` | Обновить ставку |
| DELETE | `/tax-rates/{id}` | Удалить ставку |
| PATCH | `/tax-rates/{id}/close` | Закрыть период ставки |

### Health
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Сообщение "API работает" |
| GET | `/health` | Проверка здоровья (подключение к БД) |

---

## Аутентификация и авторизация

### Механизм: JWT (HS256)
- Хеширование паролей: **PBKDF2-SHA256** через passlib
- Токен: JWT с полем `sub` = tenant_id, `exp` = время истечения (по умолчанию 30 минут)
- `SECRET_KEY` определён в `app/core/auth.py`

### Поток:
1. **Регистрация:** POST `/auth/register` → создаёт Tenant с хешированным паролем → возвращает JWT
2. **Вход:** POST `/auth/login` (OAuth2PasswordRequestForm) → проверяет пароль → возвращает JWT
3. **Защищённые эндпоинты:** `Depends(get_current_tenant)` валидирует JWT, загружает Tenant из БД

### Авторизация:
- Большинство эндпоинтов требуют аутентификации через `get_current_tenant`
- Проверка владения: пользователи могут обращаться только к данным своего тенанта
- Некоторые административные эндпоинты (создание/список тенантов) НЕ защищены аутентификацией

---

## Фоновые задачи (Celery)

### Конфигурация
- **Брокер:** `redis://<host>:6379/0`
- **Бэкенд:** `redis://<host>:6379/0`
- **Очередь:** `wb_sync` для задач синхронизации
- **Сериализатор:** JSON
- **Часовой пояс:** Europe/Moscow

### Задача: `sync_tenant_wb_data`
- Универсальная Celery-задача для синхронизации данных WB
- Параметры: `tenant_id`, `date_from`, `date_to`
- Отслеживание прогресса через `update_state()` (PROGRESS → SUCCESS/FAILURE)
- Возвращает метрики: total_time, total_records, api_calls, batches_processed, products_synced

### Задача: `weekly_sync_all_tenants`
- Запланированная еженедельная синхронизация ВСЕХ активных тенантов с WB API ключами
- Синхронизирует предыдущие 7 дней (понедельник — воскресенье)
- Создаёт отдельные задачи `sync_tenant_wb_data` для каждого тенанта
- Возвращает ID задач для отслеживания статуса

---

## Сервисы (бизнес-логика)

### WBAPIClient (`wb_api_client.py`)
- Асинхронный HTTP-клиент для API Wildberries
- **Финансовый API:** `https://statistics-api.wildberries.ru/api/v5/supplier/reportDetailByPeriod`
- **Content API:** `https://content-api.wildberries.ru/content/v2/get/cards/list`
- SSL-верификация через certifi
- Обработка rate limiting (429), ошибок аутентификации (401)

### SyncService (`sync_service.py`)
- Оркеструет полную синхронизацию данных WB
- **Пагинация:** загружает данные батчами по 100k записей через курсор `rrd_id`
- **65-секундная задержка** между вызовами API (соблюдение rate limit)
- Двухэтапный процесс: (1) синхронизация отчётов, (2) синхронизация/обогащение товаров
- Пакетная вставка в БД с подробными метриками времени

### ReportMapperService (`report_mapper.py`)
- Трансформирует сырые ответы WB API в модели `SupplierReportCreate`
- Маппинг полей: `sa_name` → `sku`, `ppvz_for_pay` → `amount_for_pay`, и т.д.
- Сохраняет полные исходные данные в поле `raw_data` (JSON)
- Обрабатывает несколько форматов дат

### ProductSyncService (`product_sync_service.py`)
- Извлекает уникальные товары из отчётов поставщика (SQL window function по SKU)
- Создаёт товары в БД, если они ещё не существуют
- Обогащает товары через WB Content API (название, описание, фото)

### AnalyticsService (`analytics_service.py`)
- Генерирует отчёты рентабельности/прибыльности
- Использует DB view `ProductMarginsMonthV`
- Рассчитывает: общую выручку, маржу, хранение, удержания, доставку, штрафы
- **Расчёт зарплаты и премии:**
  - Фиксированная зарплата: **60 000 руб** (захардкожено)
  - Премия: 5% от (маржа − расходы − (удержания − выручка×10%))
  - Маржа владельца: 10% от (маржа − расходы)
- Итоговая рентабельность = (маржа_после_зарплаты / выплаты) × 100

### DynamicReport (`report_generator.py`)
- Генератор Excel-отчётов со встроенными формулами
- Двухчастная компоновка: вертикальная (сводка KPI с формулами) + горизонтальная (таблица товаров)
- Использует `openpyxl` для генерации Excel
- 22 показателя KPI с перекрёстными SUM-формулами

### WBTokenDecoder (`wb_token_service.py`)
- Декодер JWT-токенов WB (без проверки подписи)
- Извлекает: тип токена (basic/test/personal/service), права (битовая маска), seller_id, дата истечения
- Биты прав: Content, Analytics, Prices, Marketplace, Statistics, Promotion, Reviews, Chat, Supplies, Returns, Documents, Finances, Users, Read-only

---

## Конфигурация и развёртывание

### Docker Compose
Три сервиса:
1. **db** — PostgreSQL 15 Alpine (port 5432, volumes: postgres_data, backup)
2. **redis** — Redis 7 Alpine (port 6379, maxmemory 128mb)
3. **backend** — FastAPI приложение (port 8000, код примонтирован для разработки)

### Dockerfile
- Base: `python:3.11-slim`
- Системные зависимости: gcc
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

### Запуск в разработке
```bash
# Запуск инфраструктуры
docker-compose up -d db redis

# Запуск бэкенда (из виртуального окружения)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Запуск Celery воркера
celery -A app.celery_app.celery_app worker --loglevel=info -Q wb_sync

# Запуск Flower (мониторинг Celery)
celery -A app.celery_app.celery_app flower
```

---

## Известные проблемы и технические долги

1. **Нет Alembic миграций:** Папка `alembic/versions/` пуста. Таблицы создаются через `create_all()` при старте. **Не подходит для продакшена.**

2. **Хардкодный SECRET_KEY:** `SECRET_KEY = "your-secret-key-change-in-production"` в `app/core/auth.py`. **Критическая уязвимость для продакшена.**

3. **Удалённая база данных:** `.env` указывает на внешний сервер (`94.103.91.204`), а не на локальный Docker PostgreSQL.

4. **Дубликат aiohttp:** В `new_requirements.txt` могут быть дублирующиеся версии aiohttp.

5. **Debug эндпоинт:** `/app/routers/debug.py` существует и импортирован, но закомментирован в `main.py`.

6. **Неиспользуемый эндпоинт:** `/analytics/financial-overview` возвращает заглушку.

7. **Незащищённые CRUD тенантов:** `POST /tenants/` и `PUT /tenants/{id}` НЕ защищены аутентификацией.

8. **Хардкодная зарплата:** `fixed_salary = 60000.0` захардкожена в AnalyticsService.

---

## Конвенции разработки

### Импорты
- Все импорты внутри проекта используют абсолютные пути от корня `app/`
- Пример: `from app.database.database import get_db`

### Зависимости БД
- Роутеры получают сессию БД через `Depends(get_db)`
- CRUD функции принимают `db: Session` как первый аргумент

### Pydantic схемы
- Расположены в `app/schemas/`
- Используют `model_config = ConfigDict(from_attributes=True)` для совместимости с ORM

### Многотенантность
- Все данные привязаны к `tenant_id`
- CRUD слои фильтруют по `tenant_id` текущего авторизованной сессии

### Дата-диапазоны
- `ProductCost` и `TaxRate` используют исторический подход: `start_date` + `end_date` (nullable = текущая запись)

---

## Частые сценарии разработки

### Добавление нового эндпоинта
1. Создать Pydantic схемы в `app/schemas/`
2. Создать CRUD функции в `app/crud/`
3. Создать роутер в `app/routers/`
4. Зарегистрировать роутер в `main.py` (добавить `app.include_router()`)

### Добавление новой модели
1. Создать модель в `app/models/`
2. Обновить `metadata.create_all()` (или создать Alembic миграцию)
3. Создать CRUD функции в `app/crud/`
4. Создать роутер и схемы

### Добавление фоновой задачи
1. Создать задачу в `app/tasks/` с декоратором `@celery_app.task`
2. Создать роутер для запуска задачи в `app/routers/`
3. Использовать `update_state()` для отслеживания прогресса

---

## Примечания

- Фронтенд подключается с `localhost:5173/5174` (Vite dev server — предположительно React/Vue)
- CORS настроен для `http://localhost:5173`, `http://localhost:5174` и `http://94.103.91.204:5173`
- Папка `/app/api/` существует, но пуста (зарезервирована)
- Часовой пояс Celery: Europe/Moscow
