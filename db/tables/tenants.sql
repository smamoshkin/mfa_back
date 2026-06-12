-- public.tenants определение

-- Drop table

-- DROP TABLE public.tenants;

CREATE TABLE public.tenants (
	id serial4 NOT NULL,
	"name" varchar(255) NOT NULL,
	wb_api_key varchar(500) NULL,
	ozon_api_key varchar(500) NULL,
	created_at timestamp NULL,
	is_active bool NULL,
	login_email varchar(255) NOT NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	hashed_password varchar(255) NULL,
	email_verified bool DEFAULT false NULL,
	last_login timestamp NULL,
	wb_api_key_expire_at timestamp NULL, -- Дата истечения срока действия API ключа
	CONSTRAINT tenants_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_tenants_id ON public.tenants USING btree (id);
CREATE UNIQUE INDEX ix_tenants_login_email ON public.tenants USING btree (login_email);

-- Column comments

COMMENT ON COLUMN public.tenants.wb_api_key_expire_at IS 'Дата истечения срока действия API ключа';

-- Permissions

ALTER TABLE public.tenants OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.tenants TO marketfinance_user;