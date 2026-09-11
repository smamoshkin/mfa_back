# Materialized views для Аналитики

Материализованные view, на которые опирается страница «Аналитика»
(`/analytics/rentability`) и рекламный модуль:

| Файл | Объект | Гранулярность | Назначение |
|------|--------|---------------|------------|
| `01_create_supplier_reports_agg_mv.sql` | `supplier_reports_agg_mv` | день × sku | Источник для `_get_last_synced_date` (`MAX(period_day)`). Аналог обычной view `supplier_reports_aggregated_v`. |
| `03_create_mv_wb_ad_actual_expense_by_nm_day.sql` | `mv_wb_ad_actual_expense_by_nm_day` | кампания × день × nmId | Аллокация фактических рекламных списаний `/adv/v1/upd` на nmId пропорционально `nms[].sum` из `/adv/v3/fullstats`. |
| `04_create_mv_wb_ad_actual_expense_by_nm_month.sql` | `mv_wb_ad_actual_expense_by_nm_month` | месяц × nmId | Месячные итоги аллоцированного расхода: сумма, campaigns_count, advertising_days_count. |
| `05_create_product_margins_mv.sql` | `product_margins_mv` | месяц × sku | Источник для отчёта рентабельности (`AnalyticsService._get_aggregated_data`). Строится поверх `supplier_reports_agg_mv` + LEFT JOIN рекламной месячной MV по `(tenant_id, period_month, nm_id)`. |

> Файл `02_create_product_margins_mv.sql` переименован в `05_...` (2026-09):
> product_margins_mv теперь зависит от рекламных MV 03/04, порядок применения
> должен совпадать с нумерацией файлов.

Рекламные факт-таблицы (`wb_ad_expense_operations`, `wb_ad_product_daily_stats`)
лежат в `db/tables/` и применяются ДО мат.view.

## ⚠️ Порядок релиза: СНАЧАЛА DDL, ПОТОМ код

`main.py` при старте выполняет `Base.metadata.create_all()`. Если новый код
(с ORM-моделями `WBAdActualExpenseByNmDayMV` / `WBAdActualExpenseByNmMonthMV`)
запустится РАНЬШЕ, чем применены эти DDL — create_all создаст **обычные
ТАБЛИЦИ** с именами будущих мат.view (проверено на тестовой БД 07.09.2026).
Лечится так, после чего DDL применяется заново:

```sql
DROP TABLE IF EXISTS public.mv_wb_ad_actual_expense_by_nm_day CASCADE;
DROP TABLE IF EXISTS public.mv_wb_ad_actual_expense_by_nm_month CASCADE;
```

(для существующих мат.view create_all безвреден: has_table() их видит и
пропускает).

Логика финансовых расчётов (включая `CASE` для `period_month`) перенесена из
`db/views/*.sql` **без изменений** — семантика отчётов та же. Доработка
2026-09 (реклама) только ДОБАВИЛА колонки в `product_margins_mv`
(nm_id, actual_ad_expense_amount, campaigns_count, advertising_days_count,
factual_drr_percent, margin_after_advertising), не меняя прежних.

> **Про таймзону (важно).** В `01_*.sql` `sale_dt`/`date_from`/`date_to`
> приводятся к `timestamp WITHOUT time zone` (а не `timestamp with time zone`,
> как в оригинальной обычной view), а `period_*` — к `date`. Причина:
> `date -> timestamptz` выполняется по таймзоне текущей сессии, поэтому для
> обычной view (пересчитывается в зоне читающего) это незаметно, а для
> MATERIALIZED VIEW результат «замерзает» в зоне создания/REFRESH. Если мат.view
> создана/обновлена в MSK-сессии, а читается бэкендом в UTC — `period_month`
> «съезжает» на 3 часа назад и фильтр `>= 'YYYY-MM-01'` отсекает весь месяц
> (пустой ответ `/analytics/rentability`). `timestamp without time zone` + `date`
> делает результат одинаковым в любой зоне.

Старые обычные view (`supplier_reports_aggregated_v`, `product_margins_month_v`)
**не удаляются** — их продолжает использовать `dashboard.py` и
`report_generator.py`.

### Про уникальные индексы (важно)

`REFRESH MATERIALIZED VIEW CONCURRENTLY` требует на мат.view **любой** уникальный
индекс. Естественный ключ выбирается по реальному `GROUP BY` каждой view:

- `supplier_reports_agg_mv` → `(tenant_id, period_day, period_month, sku)` —
  **4 колонки**. `period_month` обязан входить в ключ: он считается через `CASE`
  и может для одного `(tenant_id, period_day, sku)` принять два значения
  (корректировка с `sale_dt` за пределами окна отчёта WB «прицепляется» к месяцу
  `date_to`). Трёхколоночный ключ без `period_month` даёт дубли и не создаётся.
- `product_margins_mv` → `(tenant_id, period_month, sku)` — здесь `GROUP BY`
  именно по этим трём, дублей нет.

---

## Порядок применения (строго по номерам: 01 → 03 → 04 → 05)

Каждый следующий скрипт зависит от предыдущих (`product_margins_mv` читает и
из `supplier_reports_agg_mv`, и из рекламных MV). Перед мат.view применить
таблицы `db/tables/wb_ad_*.sql`.

> **Если мат.view уже были созданы предыдущей версией скриптов** — просто
> выполните оба файла заново: каждый начинается с `DROP MATERIALIZED VIEW IF
> EXISTS`, так что пересоздание безопасно. После пересоздания данные в мат.view
> обновятся (`WITH DATA`), перезапускать синк не обязательно.

### Вариант A. Через `psql`

```bash
cd marketfinanceapp

# Подставьте DATABASE_URL из .env или используйте переменную окружения.
export DATABASE_URL="postgresql://marketfinance_user:***@94.103.91.204:5432/marketfinance_db"

# Сначала факт-таблицы рекламы:
psql "$DATABASE_URL" -f db/tables/wb_ad_expense_operations.sql
psql "$DATABASE_URL" -f db/tables/wb_ad_product_daily_stats.sql
# Затем мат.view по номерам:
psql "$DATABASE_URL" -f db/materialized_views/01_create_supplier_reports_agg_mv.sql
psql "$DATABASE_URL" -f db/materialized_views/03_create_mv_wb_ad_actual_expense_by_nm_day.sql
psql "$DATABASE_URL" -f db/materialized_views/04_create_mv_wb_ad_actual_expense_by_nm_month.sql
psql "$DATABASE_URL" -f db/materialized_views/05_create_product_margins_mv.sql
```

### Вариант B. Через любой SQL-клиент (DBeaver, pgAdmin и т.п.)

Открыть и выполнить файлы по очереди в том же порядке.

> `CREATE MATERIALIZED VIEW ... WITH DATA` заполняет мат.view сразу при
> создании (это и есть первый «рефреш»). После выполнения обоих скриптов
> данные уже доступны — новый синк не требуется.

---

## Проверка после применения

```sql
-- 1. Мат.view существуют и заполнены:
SELECT count(*) FROM supplier_reports_agg_mv;
SELECT count(*) FROM product_margins_mv;

-- 2. Уникальные индексы на месте (нужны для REFRESH CONCURRENTLY):
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename IN ('supplier_reports_agg_mv', 'product_margins_mv')
ORDER BY tablename, indexname;
-- Ожидаем:
--   supplier_reports_agg_mv_uq ON (tenant_id, period_day, period_month, sku)  ← 4 колонки
--   product_margins_mv_uq      ON (tenant_id, period_month, sku)
--   mv_wb_ad_actual_expense_by_nm_day_uq   ON (tenant_id, advert_id, expense_date_msk, nm_id, currency)
--   mv_wb_ad_actual_expense_by_nm_month_uq ON (tenant_id, expense_month_msk, nm_id, currency)

-- 3. Скорость чтения — должна быть единицы мс (сотни строк вместо 160k):
EXPLAIN ANALYZE
SELECT * FROM product_margins_mv
WHERE tenant_id = 8 AND period_month >= '2026-08-01' AND period_month <= '2026-08-31';

EXPLAIN ANALYZE
SELECT max(period_day) FROM supplier_reports_agg_mv
WHERE tenant_id = 8 AND period_day >= '2026-08-01' AND period_day <= '2026-08-31';
```

После этого — перезапустить Celery-воркер и uvicorn, чтобы подхватить
обновлённые `analytics_service.py` и `sync_service.py`.

---

## Дальнейшее обновление данных

`REFRESH MATERIALIZED VIEW CONCURRENTLY` выполняется автоматически:

- `supplier_reports_agg_mv` + `product_margins_mv` — в конце каждого полного
  синка (`SyncService` → `refresh_analytics_materialized_views()`);
- рекламная цепочка `mv_wb_ad_actual_expense_by_nm_day` →
  `mv_wb_ad_actual_expense_by_nm_month` → `product_margins_mv` — после
  УСПЕШНОЙ загрузки и upd, и fullstats (`WBAdvertisingService.refresh_advertising_materialized_views`,
  advisory lock 72459103 защищает от параллельного запуска).

Ручной рефреш (если когда-нибудь понадобится):

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY supplier_reports_agg_mv;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_wb_ad_actual_expense_by_nm_day;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_wb_ad_actual_expense_by_nm_month;
REFRESH MATERIALIZED VIEW CONCURRENTLY product_margins_mv;
```

> Порядок важен и при ручном рефреше: подневная финансы → рекламные →
> помесячная рентабельность (каждая читает из предыдущих).

---

## Откат

```sql
DROP MATERIALIZED VIEW IF EXISTS public.product_margins_mv;
DROP MATERIALIZED VIEW IF EXISTS public.mv_wb_ad_actual_expense_by_nm_month;
DROP MATERIALIZED VIEW IF EXISTS public.mv_wb_ad_actual_expense_by_nm_day;
DROP MATERIALIZED VIEW IF EXISTS public.supplier_reports_agg_mv;
```

И пересоздать `product_margins_mv` прежней версией скрипта (до переименования
файла в 05 — версия из git-истории `02_create_product_margins_mv.sql`): без
рекламных MV прежний DDL работает, т.к. LEFT JOIN отсутствовал. Старые обычные
view (`supplier_reports_aggregated_v`, `product_margins_month_v`) не
затрагиваются — откат схемы не ломает dashboard/report_generator.

## Тесты

`tests/` (pytest) — разворачивают схему сами (create_all без рекламных
объектов + DDL-скрипты) и гоняют кейсы идемпотентности / аллокации / MV.
Нужен PostgreSQL (мат.view, JSONB, advisory locks) — SQLite не подходит:

```bash
# Одноразовый контейнер для тестов (стандартный DSN зашит в tests/conftest.py):
docker run -d --name faapp-test-pg \
  -e POSTGRES_DB=marketfinance_db -e POSTGRES_USER=marketfinance_user \
  -e POSTGRES_PASSWORD=marketfinance_dev -p 127.0.0.1:5433:5432 postgres:15-alpine

./venv/bin/python -m pytest tests/ -q
# или против другой БД:
TEST_DATABASE_URL=postgresql://... ./venv/bin/python -m pytest tests/ -q
```
