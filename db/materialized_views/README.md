# Materialized views для Аналитики

Две материализованные view, на которые переключается чтение страницы
«Аналитика» (`/analytics/rentability`):

| Файл | Объект | Гранулярность | Назначение |
|------|--------|---------------|------------|
| `01_create_supplier_reports_agg_mv.sql` | `supplier_reports_agg_mv` | день × sku | Источник для `_get_last_synced_date` (`MAX(period_day)`). Аналог обычной view `supplier_reports_aggregated_v`. |
| `02_create_product_margins_mv.sql` | `product_margins_mv` | месяц × sku | Источник для отчёта рентабельности (`AnalyticsService._get_aggregated_data`). Аналог обычной view `product_margins_month_v`, строится поверх `supplier_reports_agg_mv`. |

Логика расчётов (включая `CASE` для `period_month`) перенесена из
`db/views/*.sql` **без изменений** — семантика отчётов та же.

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

## Порядок применения (строго 01 → 02)

Второй скрипт зависит от первого (`product_margins_mv` строится поверх
`supplier_reports_agg_mv`).

> **Если мат.view уже были созданы предыдущей версией скриптов** — просто
> выполните оба файла заново: каждый начинается с `DROP MATERIALIZED VIEW IF
> EXISTS`, так что пересоздание безопасно. После пересоздания данные в мат.view
> обновятся (`WITH DATA`), перезапускать синк не обязательно.

### Вариант A. Через `psql`

```bash
cd marketfinanceapp

# Подставьте DATABASE_URL из .env или используйте переменную окружения.
export DATABASE_URL="postgresql://marketfinance_user:***@94.103.91.204:5432/marketfinance_db"

psql "$DATABASE_URL" -f db/materialized_views/01_create_supplier_reports_agg_mv.sql
psql "$DATABASE_URL" -f db/materialized_views/02_create_product_margins_mv.sql
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

`REFRESH MATERIALIZED VIEW CONCURRENTLY` для обеих мат.view выполняется
**автоматически в конце каждого полного синка** (`SyncService.sync_wb_data_for_period`)
— вручную запускать не нужно.

Ручной рефреш (если когда-нибудь понадобится):

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY supplier_reports_agg_mv;
REFRESH MATERIALIZED VIEW CONCURRENTLY product_margins_mv;
```

> Порядок важен и при ручном рефреше: сначала подневная, потом помесячная
> (последняя читает из первой).

---

## Откат

```sql
DROP MATERIALIZED VIEW IF EXISTS public.product_margins_mv;
DROP MATERIALIZED VIEW IF EXISTS public.supplier_reports_agg_mv;
```

После этого откатить изменения в `analytics_service.py` (вернуть
`ProductMarginsMonthV` / `SupplierReportsAggregatedV`) — и чтение снова
пойдёт из обычных view. Старые view и весь остальной код при этом
не затрагиваются.
