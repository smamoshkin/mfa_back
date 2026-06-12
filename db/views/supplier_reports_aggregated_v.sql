-- public.supplier_reports_aggregated_v исходный текст

CREATE OR REPLACE VIEW public.supplier_reports_aggregated_v
AS SELECT sr.tenant_id,
    date_trunc('day'::text, sr.sale_dt::timestamp with time zone) AS period_day,
    date_trunc('week'::text, sr.sale_dt::timestamp with time zone) AS period_week,
        CASE
            WHEN date_trunc('month'::text, sr.sale_dt::timestamp with time zone) < date_trunc('month'::text, sr.date_from::timestamp with time zone) OR date_trunc('month'::text, sr.sale_dt::timestamp with time zone) > date_trunc('month'::text, sr.date_to::timestamp with time zone) THEN date_trunc('month'::text, sr.date_to::timestamp with time zone)
            ELSE date_trunc('month'::text, sr.sale_dt::timestamp with time zone)
        END AS period_month,
    date_trunc('quarter'::text, sr.sale_dt::timestamp with time zone) AS period_quarter,
    date_trunc('year'::text, sr.sale_dt::timestamp with time zone) AS period_year,
    p.name AS product_name,
    sr.sku,
    sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Продажа'::text THEN 0
            ELSE sr.quantity
        END) AS quantity_sold,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.retail_amount
            ELSE 0::numeric
        END) AS revenue,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.amount_for_pay
            ELSE 0::numeric
        END) AS seller_payout,
    max(sr.retail_price) AS retail_price_max,
    sum(sr.storage_fee) AS storage_fee,
    sum(
        CASE
            WHEN sr.bonus_type_name ~~* '%джем%'::text OR sr.bonus_type_name ~~* '%dzhem%'::text THEN 0::numeric
            ELSE sr.deduction
        END) AS regular_deduction,
    sum(
        CASE
            WHEN sr.bonus_type_name ~~* '%джем%'::text OR sr.bonus_type_name ~~* '%dzhem%'::text THEN sr.deduction
            ELSE 0::numeric
        END) AS dzhem_deduction,
    sum(sr.delivery_rub) AS delivery_rub,
    sum(sr.penalty) AS penalty,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Платная приемка'::text THEN sr.acceptance
            ELSE 0::numeric
        END) AS acceptance,
    sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Возврат'::text THEN 0
            ELSE sr.quantity
        END) AS return_quantity,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Возврат'::text THEN sr.retail_amount
            ELSE 0::numeric
        END) AS return_revenue,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.retail_amount * tr.tax_rate / 100::numeric
            ELSE 0::numeric
        END) AS tax,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.amount_for_pay - sr.retail_amount * tr.tax_rate / 100::numeric
            ELSE 0::numeric
        END) AS payout_after_tax,
    max(COALESCE(pc.cost, 0::numeric)) AS cost_per_unit,
    sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Продажа'::text THEN 0
            ELSE sr.quantity
        END)::numeric * max(COALESCE(pc.cost, 0::numeric)) AS total_cost,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.amount_for_pay - sr.retail_amount * tr.tax_rate / 100::numeric
            ELSE 0::numeric
        END) - sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Продажа'::text THEN 0
            ELSE sr.quantity
        END)::numeric * max(COALESCE(pc.cost, 0::numeric)) - sum(sr.delivery_rub) - sum(sr.penalty) - sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Платная приемка'::text THEN sr.acceptance
            ELSE 0::numeric
        END) - sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Возврат'::text THEN sr.retail_amount
            ELSE 0::numeric
        END) AS margin
   FROM supplier_reports sr
     LEFT JOIN tax_rates tr ON sr.sale_dt >= tr.start_date AND sr.sale_dt <= COALESCE(tr.end_date, '9999-01-01'::date)
     LEFT JOIN products p ON p.sku::text = sr.sku::text AND p.tenant_id = sr.tenant_id
     LEFT JOIN LATERAL ( SELECT pc_1.cost
           FROM product_costs pc_1
          WHERE pc_1.product_id = p.id AND pc_1.start_date <= COALESCE(sr.sale_dt::timestamp with time zone, CURRENT_DATE::timestamp with time zone) AND (pc_1.end_date IS NULL OR pc_1.end_date >= COALESCE(sr.sale_dt::timestamp with time zone, CURRENT_DATE::timestamp with time zone))
          ORDER BY pc_1.start_date DESC
         LIMIT 1) pc ON true
  WHERE sr.sku::text <> ''::text AND sr.sku IS NOT NULL
  GROUP BY sr.tenant_id, (date_trunc('day'::text, sr.sale_dt::timestamp with time zone)), (date_trunc('week'::text, sr.sale_dt::timestamp with time zone)), (
        CASE
            WHEN date_trunc('month'::text, sr.sale_dt::timestamp with time zone) < date_trunc('month'::text, sr.date_from::timestamp with time zone) OR date_trunc('month'::text, sr.sale_dt::timestamp with time zone) > date_trunc('month'::text, sr.date_to::timestamp with time zone) THEN date_trunc('month'::text, sr.date_to::timestamp with time zone)
            ELSE date_trunc('month'::text, sr.sale_dt::timestamp with time zone)
        END), (date_trunc('quarter'::text, sr.sale_dt::timestamp with time zone)), (date_trunc('year'::text, sr.sale_dt::timestamp with time zone)), p.name, sr.sku;

-- Permissions

ALTER TABLE public.supplier_reports_aggregated_v OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.supplier_reports_aggregated_v TO marketfinance_user;