-- public.products определение

-- Drop table

-- DROP TABLE public.products;

CREATE TABLE public.products (
	id serial4 NOT NULL,
	tenant_id int4 NOT NULL,
	sku varchar(100) NOT NULL,
	marketplace_sku varchar(100) NOT NULL,
	foto varchar(100) NULL,
	barcode varchar(100) NULL,
	"name" varchar(500) NULL,
	category varchar(255) NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
	description text NULL,
	is_active bool NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT products_pkey PRIMARY KEY (id),
	CONSTRAINT uix_tenant_sku UNIQUE (tenant_id, sku)
);
CREATE INDEX ix_products_id ON public.products USING btree (id);

-- Permissions

ALTER TABLE public.products OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.products TO marketfinance_user;


-- public.products внешние включи

ALTER TABLE public.products ADD CONSTRAINT products_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id);