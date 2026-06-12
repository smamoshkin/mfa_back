-- public.product_margins_month_v исходный текст

CREATE OR REPLACE VIEW public.product_margins_month_v
AS SELECT p.tenant_id,
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
   FROM supplier_reports_aggregated_v p
  WHERE 1 = 1
  GROUP BY p.tenant_id, p.period_month, p.product_name, p.sku;

-- Permissions

ALTER TABLE public.product_margins_month_v OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.product_margins_month_v TO marketfinance_user;