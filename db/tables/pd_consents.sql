-- public.pd_consents — журнал согласий на обработку персональных данных (152-ФЗ).
--
-- Фиксирует факт, версию текста и обстоятельства согласия: пишется при каждой
-- регистрации (галка согласия на фронте блокирует «Создать аккаунт», поэтому
-- успешная регистрация = согласие дано). При споре/проверке РКН запись из этой
-- таблицы — доказательство: какой версией текста (docs/legal/02-consent-pd.md
-- во фронте), когда и с какого IP/браузера соглашался пользователь.
--
-- consent_type: 'pd' — согласие на обработку ПД при регистрации;
--               'marketing' — рекламная рассылка (задел на будущее, ст. 18 ФЗ «О рекламе»).
--
-- Раскатка на прод — вручную (конвенция проекта), модель: app/models/pd_consent.py.
-- Применяя после деплоя, учтите: create_all() при старте приложения создаёт
-- таблицу сам, если её ещё нет, — скрипт идемпотентен (IF NOT EXISTS).
-- Пример: docker compose exec -T db psql -U marketfinance_user -d marketfinance_db < db/tables/pd_consents.sql

CREATE TABLE IF NOT EXISTS public.pd_consents (
	id serial4 NOT NULL,
	tenant_id int4 NOT NULL,
	consent_type varchar(50) NOT NULL,        -- 'pd' | 'marketing'
	text_version varchar(50) NOT NULL,        -- версия текста согласия, напр. '1.0'
	consented_at timestamptz DEFAULT now() NOT NULL,
	ip_address varchar(100) NULL,             -- первый hop из X-Forwarded-For
	user_agent varchar(500) NULL,
	CONSTRAINT pd_consents_pkey PRIMARY KEY (id),
	CONSTRAINT pd_consents_tenant_id_fkey FOREIGN KEY (tenant_id)
		REFERENCES tenants(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_pd_consents_tenant_id ON public.pd_consents USING btree (tenant_id);

ALTER TABLE public.pd_consents OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.pd_consents TO marketfinance_user;
