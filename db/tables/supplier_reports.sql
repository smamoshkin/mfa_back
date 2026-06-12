-- public.supplier_reports определение

-- Drop table

-- DROP TABLE public.supplier_reports;

CREATE TABLE public.supplier_reports (
	id bigserial NOT NULL,
	tenant_id int4 NOT NULL,
	realizationreport_id int8 NULL,
	rrd_id int8 NULL,
	date_from date NOT NULL,
	date_to date NOT NULL,
	sale_dt date NOT NULL,
	sku varchar(100) NOT NULL,
	doc_type_name varchar(1000) NOT NULL,
	supplier_oper_name varchar(1000) NOT NULL,
	quantity int4 NULL,
	retail_amount numeric(10, 2) NULL,
	amount_for_pay numeric(10, 2) NULL,
	retail_price numeric(10, 2) NULL,
	storage_fee numeric(10, 2) NULL,
	bonus_type_name text NOT NULL,
	deduction numeric(10, 2) NULL,
	delivery_rub numeric(10, 2) NULL,
	penalty numeric(10, 2) NULL,
	acceptance numeric(10, 2) NULL,
	raw_data json NULL,
	extracted_fields json NULL,
	created_at timestamp NULL,
	CONSTRAINT supplier_reports_pkey PRIMARY KEY (id)
);

-- Permissions

ALTER TABLE public.supplier_reports OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.supplier_reports TO marketfinance_user;