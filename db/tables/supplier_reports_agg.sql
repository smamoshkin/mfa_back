-- public.supplier_reports_agg — подневная агрегация продаж (TODO №1: таблица
-- вместо материализованной view supplier_reports_agg_mv).
--
-- Заполняется кодом приложения: aggregates_service.recompute_supplier_agg()
-- выполняет DELETE затронутых месяцев + INSERT...SELECT из supplier_reports
-- (тот же SQL, что был в теле MV 01, включая CASE-коррекцию period_month).
-- Триггеры пересчёта: полный синк, импорт/правка себестоимостей, изменение
-- налоговых ставок.
--
-- Зерно / PK: (tenant_id, period_day, period_month, sku) — period_month входит
-- в ключ, т.к. считается через CASE и для одного (tenant, day, sku) может
-- принять два значения (см. комментарии в db/materialized_views/01_*.sql).
--
-- Применяется вручную (конвенция проекта). ORM: app/models/analytics_tables.py
-- (info={'skip_create_all': True} — create_all её не создаёт).

CREATE TABLE IF NOT EXISTS public.supplier_reports_agg (
    tenant_id int4 NOT NULL,
    period_day date NOT NULL,
    period_week date NOT NULL,
    period_month date NOT NULL,
    period_quarter date NOT NULL,
    period_year date NOT NULL,
    product_name text NULL,
    sku varchar(100) NOT NULL,

    quantity_sold int4 NULL,
    revenue numeric NULL,
    seller_payout numeric NULL,
    retail_price_max numeric NULL,
    storage_fee numeric NULL,
    regular_deduction numeric NULL,
    dzhem_deduction numeric NULL,
    delivery_rub numeric NULL,
    penalty numeric NULL,
    acceptance numeric NULL,
    return_quantity int4 NULL,
    return_revenue numeric NULL,

    tax numeric NULL,
    payout_after_tax numeric NULL,
    cost_per_unit numeric NULL,
    total_cost numeric NULL,
    margin numeric NULL,

    CONSTRAINT supplier_reports_agg_pkey PRIMARY KEY (tenant_id, period_day, period_month, sku)
);

CREATE INDEX IF NOT EXISTS ix_supplier_reports_agg_tenant_month
    ON public.supplier_reports_agg USING btree (tenant_id, period_month);
CREATE INDEX IF NOT EXISTS ix_supplier_reports_agg_tenant_day
    ON public.supplier_reports_agg USING btree (tenant_id, period_day);

ALTER TABLE public.supplier_reports_agg OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.supplier_reports_agg TO marketfinance_user;
