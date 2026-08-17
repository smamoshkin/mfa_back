-- 02_create_product_margins_mv.sql
-- ============================================================================
-- Помесячная материализованная view — источник для отчёта рентабельности
-- (AnalyticsService._get_aggregated_data) и оборачиваемости.
--
-- Логика GROUP BY и все вычисляемые показатели (margin_percent_revenue,
-- margin_per_unit, logistics_per_unit и т.д.) перенесены из
-- db/views/product_margins_month_v.sql БЕЗ ИЗМЕНЕНИЙ.
--
-- Единственное отличие от оригинальной обычной view: вместо
--   FROM supplier_reports_aggregated_v   -- обычная view, пересчитывается при каждом селекте
-- здесь
--   FROM supplier_reports_agg_mv          -- материализованная view из 01_*.sql
-- то есть помесячная агрегация строится поверх уже посчитанных подневных
-- агрегатов, а не пересчитывается «в лоб» по supplier_reports каждый раз.
--
-- ВАЖНО: применять строго после 01_create_supplier_reports_agg_mv.sql.
--
-- period_month здесь берётся напрямую из supplier_reports_agg_mv (без
-- дополнительного date_trunc), поэтому его тип наследуется от источника.
-- В 01_*.sql period_month уже приведён к date — здесь отдельно кастить не нужно.
-- Если в 01_*.sql тип period_month изменится — он автоматически изменится и здесь.
-- ============================================================================

DROP MATERIALIZED VIEW IF EXISTS public.product_margins_mv;

CREATE MATERIALIZED VIEW public.product_margins_mv
AS
SELECT p.tenant_id,
    p.period_month,
    p.product_name,
    p.sku,
    sum(p.quantity_sold) AS quantity_sold,
    sum(p.revenue) AS revenue,
    sum(p.seller_payout) AS seller_payout,
    max(p.retail_price_max) AS retail_price_max,
    sum(p.tax) AS tax,
    sum(p.payout_after_tax) AS payout_after_tax,
    max(p.cost_per_unit) AS cost_per_unit,
    sum(p.total_cost) AS total_cost,
    sum(p.storage_fee) AS storage_fee,
    sum(p.regular_deduction) AS regular_deduction,
    sum(p.dzhem_deduction) AS dzhem_deduction,
    sum(p.delivery_rub) AS delivery_rub,
    sum(p.penalty) AS penalty,
    sum(p.acceptance) AS acceptance,
    sum(p.return_quantity) AS return_quantity,
    sum(p.return_revenue) AS return_revenue,
    sum(p.margin) AS margin,
        CASE
            WHEN sum(p.revenue) = 0::numeric THEN 0::numeric
            ELSE sum(p.margin) / sum(p.revenue) * 100::numeric
        END AS margin_percent_revenue,
        CASE
            WHEN sum(p.seller_payout) = 0::numeric THEN 0::numeric
            ELSE sum(p.margin) / sum(p.seller_payout) * 100::numeric
        END AS margin_percent_payout,
        CASE
            WHEN sum(p.quantity_sold) = 0::numeric THEN 0::numeric
            ELSE sum(p.delivery_rub) / sum(p.quantity_sold)
        END AS logistics_per_unit,
        CASE
            WHEN sum(p.quantity_sold) = 0::numeric THEN 0::numeric
            ELSE sum(p.margin) / sum(p.quantity_sold)
        END AS margin_per_unit
   FROM supplier_reports_agg_mv p
  WHERE 1 = 1
  GROUP BY p.tenant_id, p.period_month, p.product_name, p.sku
WITH DATA;

-- Уникальный индекс: обязателен для REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- (tenant_id, period_month, sku) — естественный ключ помесячной агрегации.
CREATE UNIQUE INDEX product_margins_mv_uq
    ON public.product_margins_mv (tenant_id, period_month, sku);

-- Permissions — аналогично существующим view.
ALTER TABLE public.product_margins_mv OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.product_margins_mv TO marketfinance_user;
