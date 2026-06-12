-- public.tax_rates определение

-- Drop table

-- DROP TABLE public.tax_rates;

CREATE TABLE public.tax_rates (
	id serial4 NOT NULL,
	tenant_id int4 NOT NULL,
	tax_rate numeric(5, 2) NOT NULL,
	start_date date NOT NULL,
	end_date date NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
	created_by varchar(100) NULL,
	CONSTRAINT tax_rates_date_check CHECK (((end_date IS NULL) OR (end_date > start_date))),
	CONSTRAINT tax_rates_pkey PRIMARY KEY (id),
	CONSTRAINT tax_rates_rate_check CHECK (((tax_rate >= (0)::numeric) AND (tax_rate <= (100)::numeric))),
	CONSTRAINT tax_rates_unique_period UNIQUE (tenant_id, start_date, end_date)
);
CREATE INDEX ix_tax_rates_date_range ON public.tax_rates USING btree (start_date, end_date);
CREATE INDEX ix_tax_rates_id ON public.tax_rates USING btree (id);
CREATE INDEX ix_tax_rates_tenant_id ON public.tax_rates USING btree (tenant_id);

-- Permissions

ALTER TABLE public.tax_rates OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.tax_rates TO marketfinance_user;


-- public.tax_rates внешние включи

ALTER TABLE public.tax_rates ADD CONSTRAINT tax_rates_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;