-- public.wb_ad_expense_operations — сырые фактические списания Wildberries
-- из рекламного API GET /adv/v1/upd.
--
-- Одна строка = одна исходная операция списания из ответа WB.
-- Фактическая сумма списания — updSum; дата/месяц расхода — календарный
-- день и месяц updTime в Europe/Moscow (посчитаны при записи, хранятся
-- отдельными колонками, чтобы агрегации не зависели от таймзоны сессии).
--
-- Идемпотентность: идентичность траты = (tenant_id, advert_id,
-- expense_datetime, expense_amount) — updNum ИСКЛЮЧЁН из идентичности: WB отдаёт
-- одну и ту же трату то с updNum=0 (УПД не сформирован), то с реальным
-- номером УПД. source_hash = sha256 этой идентичности (UNIQUE ниже).
-- ⚠️ История 14.09.2026: хэш по всей записи (с updNum) давал дубли —
--    одна и та же трата возвращалась API с разными updNum.
--
-- Применяется вручную (конвенция проекта), модель: app/models/wb_advertising.py.
-- Денежные суммы — только NUMERIC (никаких float).

CREATE TABLE IF NOT EXISTS public.wb_ad_expense_operations (
    id bigserial NOT NULL,
    tenant_id int4 NOT NULL,
    advert_id int8 NOT NULL,

    expense_datetime timestamptz NOT NULL,     -- исходное updTime как есть
    expense_date_msk date NOT NULL,            -- дата updTime в Europe/Moscow
    expense_month_msk date NOT NULL,           -- первое число месяца expense_date_msk

    expense_amount numeric(14, 2) NOT NULL,    -- updSum как Decimal
    currency varchar(10) NOT NULL DEFAULT 'RUB',

    wb_upd_num int8 NULL,                      -- updNum (не уникален, может быть 0)
    campaign_name varchar(500) NULL,           -- campName
    payment_type varchar(100) NULL,            -- paymentType
    advert_type int4 NULL,                     -- advertType
    advert_status int4 NULL,                   -- advertStatus

    source_hash varchar(64) NOT NULL,          -- sha256 канонического JSON записи WB
    raw_payload jsonb NOT NULL,                -- исходная запись WB целиком

    synced_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT wb_ad_expense_operations_pkey PRIMARY KEY (id),
    CONSTRAINT wb_ad_expense_operations_tenant_id_fkey FOREIGN KEY (tenant_id)
        REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT uq_wb_ad_expense_ops_tenant_hash UNIQUE (tenant_id, source_hash),
    CONSTRAINT uq_wb_ad_expense_ops_charge UNIQUE (tenant_id, advert_id, expense_datetime, expense_amount),
    CONSTRAINT ck_wb_ad_expense_ops_amount_nonneg CHECK (expense_amount >= 0)
);

CREATE INDEX IF NOT EXISTS ix_wb_ad_expense_ops_tenant_date ON public.wb_ad_expense_operations
    USING btree (tenant_id, expense_date_msk);
CREATE INDEX IF NOT EXISTS ix_wb_ad_expense_ops_tenant_month ON public.wb_ad_expense_operations
    USING btree (tenant_id, expense_month_msk);
CREATE INDEX IF NOT EXISTS ix_wb_ad_expense_ops_tenant_advert_date ON public.wb_ad_expense_operations
    USING btree (tenant_id, advert_id, expense_date_msk);

ALTER TABLE public.wb_ad_expense_operations OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.wb_ad_expense_operations TO marketfinance_user;
