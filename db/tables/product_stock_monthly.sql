-- public.product_stock_monthly определение

-- Drop table

-- DROP TABLE public.product_stock_monthly;

CREATE TABLE public.product_stock_monthly (
	id serial4 NOT NULL,
	tenant_id int4 NOT NULL,
	sku varchar(100) NOT NULL,
	nm_id varchar(100) NOT NULL,
	period_month date NOT NULL,
	quantity int4 DEFAULT 0 NOT NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT product_stock_monthly_pkey PRIMARY KEY (id),
	CONSTRAINT uix_tenant_sku_period UNIQUE (tenant_id, sku, period_month)
);
CREATE INDEX ix_product_stock_monthly_id ON public.product_stock_monthly USING btree (id);
CREATE INDEX ix_product_stock_monthly_period_month ON public.product_stock_monthly USING btree (period_month);

-- Permissions

ALTER TABLE public.product_stock_monthly OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.product_stock_monthly TO marketfinance_user;


-- public.product_stock_monthly внешние включи

ALTER TABLE public.product_stock_monthly ADD CONSTRAINT product_stock_monthly_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;
