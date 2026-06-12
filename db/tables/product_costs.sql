-- public.product_costs определение

-- Drop table

-- DROP TABLE public.product_costs;

CREATE TABLE public.product_costs (
	id serial4 NOT NULL,
	product_id int4 NOT NULL,
	"cost" numeric(10, 2) NOT NULL,
	start_date date NOT NULL,
	end_date date NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
	created_by varchar(100) NULL,
	CONSTRAINT product_costs_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_product_costs_id ON public.product_costs USING btree (id);

-- Permissions

ALTER TABLE public.product_costs OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.product_costs TO marketfinance_user;


-- public.product_costs внешние включи

ALTER TABLE public.product_costs ADD CONSTRAINT product_costs_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.products(id);