-- public.auth_tokens — одноразовые токены подтверждения email и сброса пароля.
--
-- Токен в открытом виде существует только в письме пользователя; в БД
-- хранится ТОЛЬКО sha256-хэш. Токены одноразовые (used_at), с TTL
-- (verify — 48 часов, reset — 60 минут; проверяется кодом приложения).
--
-- Применяется вручную (конвенция проекта), модель: app/models/auth_token.py.

CREATE TABLE public.auth_tokens (
	id serial4 NOT NULL,
	tenant_id int4 NOT NULL,
	token_hash varchar(64) NOT NULL,          -- sha256 hex
	purpose varchar(10) NOT NULL,             -- 'verify' | 'reset'
	expires_at timestamptz NOT NULL,
	used_at timestamptz NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT auth_tokens_pkey PRIMARY KEY (id),
	CONSTRAINT auth_tokens_token_hash_key UNIQUE (token_hash),
	CONSTRAINT auth_tokens_tenant_id_fkey FOREIGN KEY (tenant_id)
		REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_tokens_tenant_purpose ON public.auth_tokens USING btree (tenant_id, purpose);

ALTER TABLE public.auth_tokens OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.auth_tokens TO marketfinance_user;
