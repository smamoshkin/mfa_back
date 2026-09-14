-- public.product_margins — помесячная рентабельность по артикулам (TODO №1:
-- таблица вместо материализованной view product_margins_mv).
--
-- Заполняется кодом приложения: aggregates_service.recompute_product_margins()
-- выполняет DELETE затронутых месяцев + INSERT...SELECT из
-- supplier_reports_agg (таблица) + products (nm_id) + рекламной месячной MV
-- mv_wb_ad_actual_expense_by_nm_month (распределение фактической рекламы
-- между sku-дублями карточки пропорционально выручке).
--
-- Зерно / PK: (tenant_id, period_month, sku).
--
-- Применяется вручную (конвенция проекта). ORM: app/models/analytics_tables.py
-- (info={'skip_create_all': True} — create_all её не создаёт).

CREATE TABLE IF NOT EXISTS public.product_margins (
    tenant_id int4 NOT NULL,
    period_month date NOT NULL,
    product_name text NULL,
    sku varchar(100) NOT NULL,
    nm_id int8 NULL,                                -- nmId WB (products.marketplace_sku)

    quantity_sold int4 NULL,
    revenue numeric NULL,
    seller_payout numeric NULL,
    retail_price_max numeric NULL,
    tax numeric NULL,
    payout_after_tax numeric NULL,
    cost_per_unit numeric NULL,
    total_cost numeric NULL,
    storage_fee numeric NULL,
    regular_deduction numeric NULL,
    dzhem_deduction numeric NULL,
    delivery_rub numeric NULL,
    penalty numeric NULL,
    acceptance numeric NULL,
    return_quantity int4 NULL,
    return_revenue numeric NULL,
    margin numeric NULL,
    margin_percent_revenue numeric NULL,
    margin_percent_payout numeric NULL,
    logistics_per_unit numeric NULL,
    margin_per_unit numeric NULL,

    -- Реклама (фактические списания, аллоцированные на артикул)
    actual_ad_expense_amount numeric(14, 2) NOT NULL DEFAULT 0,
    campaigns_count int4 NOT NULL DEFAULT 0,
    advertising_days_count int4 NOT NULL DEFAULT 0,
    factual_drr_percent numeric NULL,               -- NULL при выручке <= 0
    margin_after_advertising numeric NULL,

    CONSTRAINT product_margins_pkey PRIMARY KEY (tenant_id, period_month, sku)
);

CREATE INDEX IF NOT EXISTS ix_product_margins_tenant_nm_month
    ON public.product_margins USING btree (tenant_id, nm_id, period_month);

ALTER TABLE public.product_margins OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.product_margins TO marketfinance_user;
