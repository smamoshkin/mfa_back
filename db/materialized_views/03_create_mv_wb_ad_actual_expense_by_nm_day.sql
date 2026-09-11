-- 03_create_mv_wb_ad_actual_expense_by_nm_day.sql
-- ============================================================================
-- Дневная аллокация ФАКТИЧЕСКИХ рекламных списаний (/adv/v1/upd, поле updSum)
-- на рекламируемые nmId пропорционально расходам детализации
-- (/adv/v3/fullstats, поле nms[].sum).
--
-- Зерно: tenant_id + advert_id + expense_date_msk + nm_id + currency.
--
-- Формула:
--   allocated = actual_upd_expense(кампания, день)
--               * fullstats_spend(nmId, кампания, день)
--                 / fullstats_spend(все ПЛАТНЫЕ nmId кампании за день)
--
-- Ассоциированные артикулы (nms[].sum = 0 при наличии заказов/корзин) в
-- распределение не попадают — строки с fullstats_nm_spend_amount <= 0
-- исключаются до соединения.
--
-- Денежное округление (инвариант SUM(allocated) = actual с точностью 0.01):
--   всем nmId группы, КРОМЕ ПОСЛЕДНЕГО, достаётся ROUND(доли, 2);
--   последний nmId группы получает actual − сумма округлённых долей остальных.
--   «Последний» = детерминированный порядок по nm_id (ROW_NUMBER).
--   Группа = tenant_id + advert_id + expense_date_msk + currency.
--
-- Кампании/дни, где списание есть, а платной детализации нет (и наоборот),
-- в MV не попадают: аллокировать нечего или не на что.
--
-- Уникальный индекс обязателен для REFRESH ... CONCURRENTLY.
-- Зависит от таблиц: wb_ad_expense_operations, wb_ad_product_daily_stats
-- (файлы db/tables/ — применяются ДО этой MV).
-- ============================================================================

-- На случай повторного применения: сначала drop. CASCADE — потому что на эту
-- мат.view ссылается mv_wb_ad_actual_expense_by_nm_month (файл 04); без CASCADE
-- повторный прогон упадёт. Обе мат.view пересоздаются скриптами сразу после.
DROP MATERIALIZED VIEW IF EXISTS public.mv_wb_ad_actual_expense_by_nm_day CASCADE;

CREATE MATERIALIZED VIEW public.mv_wb_ad_actual_expense_by_nm_day
AS
WITH upd_expenses AS (
    -- Фактические списания, агрегированные до зерна MV
    SELECT e.tenant_id,
           e.advert_id,
           e.expense_date_msk,
           min(e.expense_month_msk) AS expense_month_msk,   -- внутри одного дня месяц один
           e.currency,
           sum(e.expense_amount) AS actual_expense_amount
    FROM wb_ad_expense_operations e
    GROUP BY e.tenant_id, e.advert_id, e.expense_date_msk, e.currency
),
fullstats_nm AS (
    -- Товарный расход fullstats: nms[].sum, суммированный по всем app_type
    SELECT s.tenant_id,
           s.advert_id,
           s.stat_date_msk,
           s.nm_id,
           s.currency,
           sum(s.stat_spend_amount) AS fullstats_nm_spend_amount
    FROM wb_ad_product_daily_stats s
    GROUP BY s.tenant_id, s.advert_id, s.stat_date_msk, s.nm_id, s.currency
),
paid_fullstats_nm AS (
    -- Только nmId с реальным расходом (> 0) — исключает ассоциированные артикулы
    SELECT f.*
    FROM fullstats_nm f
    WHERE f.fullstats_nm_spend_amount > 0
),
joined AS (
    -- Списание ↔ детализация: совпадающий день кампании. INNER: без весов
    -- аллокация невозможна, без списания аллокировать нечего.
    SELECT e.tenant_id,
           e.advert_id,
           e.expense_date_msk,
           e.expense_month_msk,
           e.currency,
           e.actual_expense_amount,
           f.nm_id,
           f.fullstats_nm_spend_amount
    FROM upd_expenses e
    JOIN paid_fullstats_nm f
      ON f.tenant_id = e.tenant_id
     AND f.advert_id = e.advert_id
     AND f.stat_date_msk = e.expense_date_msk
     AND f.currency = e.currency
),
weighted AS (
    SELECT j.*,
           sum(j.fullstats_nm_spend_amount) OVER (
               PARTITION BY j.tenant_id, j.advert_id, j.expense_date_msk, j.currency
           ) AS fullstats_total_spend_amount,
           row_number() OVER (
               PARTITION BY j.tenant_id, j.advert_id, j.expense_date_msk, j.currency
               ORDER BY j.nm_id
           ) AS rn,
           count(*) OVER (
               PARTITION BY j.tenant_id, j.advert_id, j.expense_date_msk, j.currency
           ) AS nm_count
    FROM joined j
),
allocated AS (
    SELECT w.*,
           CASE
               WHEN w.rn < w.nm_count THEN
                   round(w.actual_expense_amount * w.fullstats_nm_spend_amount
                         / w.fullstats_total_spend_amount, 2)
               ELSE
                   -- последний nmId группы получает остаток копеек:
                   -- факт минус сумма округлённых долей остальных
                   w.actual_expense_amount
                   - coalesce(sum(
                         round(w.actual_expense_amount * w.fullstats_nm_spend_amount
                               / w.fullstats_total_spend_amount, 2)
                     ) FILTER (WHERE w.rn < w.nm_count) OVER (
                         PARTITION BY w.tenant_id, w.advert_id, w.expense_date_msk, w.currency
                     ), 0::numeric)
           END AS allocated_actual_expense_amount
    FROM weighted w
)
SELECT a.tenant_id,
       a.advert_id,
       a.expense_date_msk,
       a.expense_month_msk,
       a.nm_id,
       a.currency,
       a.actual_expense_amount,
       a.fullstats_nm_spend_amount,
       a.fullstats_total_spend_amount,
       a.fullstats_nm_spend_amount / a.fullstats_total_spend_amount AS allocation_weight,
       a.allocated_actual_expense_amount,
       a.actual_expense_amount - a.fullstats_total_spend_amount AS reconciliation_delta_amount
FROM allocated a
WITH DATA;

-- Уникальный индекс — зерну MV, обязателен для REFRESH CONCURRENTLY.
CREATE UNIQUE INDEX mv_wb_ad_actual_expense_by_nm_day_uq
    ON public.mv_wb_ad_actual_expense_by_nm_day (tenant_id, advert_id, expense_date_msk, nm_id, currency);

CREATE INDEX ix_mv_wb_ad_day_tenant_nm_date
    ON public.mv_wb_ad_actual_expense_by_nm_day (tenant_id, nm_id, expense_date_msk);

CREATE INDEX ix_mv_wb_ad_day_tenant_month_nm
    ON public.mv_wb_ad_actual_expense_by_nm_day (tenant_id, expense_month_msk, nm_id);

ALTER TABLE public.mv_wb_ad_actual_expense_by_nm_day OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.mv_wb_ad_actual_expense_by_nm_day TO marketfinance_user;
