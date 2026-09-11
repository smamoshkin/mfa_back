-- 04_create_mv_wb_ad_actual_expense_by_nm_month.sql
-- ============================================================================
-- Помесячная агрегация аллоцированных фактических рекламных расходов по
-- артикулу — быстрые итоги для соединения с MV рентабельности.
--
-- Источник: mv_wb_ad_actual_expense_by_nm_day (файл 03 — применяется ДО этой).
-- Зерно: tenant_id + expense_month_msk + nm_id + currency.
--
-- campaigns_count        — COUNT(DISTINCT advert_id): сколько кампаний
--                          «тратились» на артикул в месяце.
-- advertising_days_count — COUNT(DISTINCT expense_date_msk): сколько дней
--                          месяца по артикулу была аллокация.
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS public.mv_wb_ad_actual_expense_by_nm_month;

CREATE MATERIALIZED VIEW public.mv_wb_ad_actual_expense_by_nm_month
AS
SELECT d.tenant_id,
       d.expense_month_msk,
       d.nm_id,
       d.currency,
       sum(d.allocated_actual_expense_amount) AS allocated_actual_ad_expense_amount,
       count(DISTINCT d.advert_id) AS campaigns_count,
       count(DISTINCT d.expense_date_msk) AS advertising_days_count
FROM mv_wb_ad_actual_expense_by_nm_day d
GROUP BY d.tenant_id, d.expense_month_msk, d.nm_id, d.currency
WITH DATA;

-- Уникальный индекс — зерну MV, обязателен для REFRESH CONCURRENTLY.
CREATE UNIQUE INDEX mv_wb_ad_actual_expense_by_nm_month_uq
    ON public.mv_wb_ad_actual_expense_by_nm_month (tenant_id, expense_month_msk, nm_id, currency);

CREATE INDEX ix_mv_wb_ad_month_tenant_nm_month
    ON public.mv_wb_ad_actual_expense_by_nm_month (tenant_id, nm_id, expense_month_msk);

ALTER TABLE public.mv_wb_ad_actual_expense_by_nm_month OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.mv_wb_ad_actual_expense_by_nm_month TO marketfinance_user;
