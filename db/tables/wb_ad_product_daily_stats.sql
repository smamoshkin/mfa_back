-- public.wb_ad_product_daily_stats — дневная детализация рекламной статистики
-- по товару из GET /adv/v3/fullstats.
--
-- Зерно: tenant_id + advert_id + stat_date_msk + app_type + nm_id.
-- Один nmId может встречаться в нескольких appType — строки хранятся
-- отдельно, при агрегации по артикулу суммируются (см. MV аллокации).
--
-- Единственный товарный расход — nms[].sum (stat_spend_amount).
-- Верхнеуровневые days[].sum и apps[].sum НЕ являются товарным расходом и
-- в таблицу не пишутся (защита от двойного учёта).
-- attributed_orders_amount — nms[].sum_price (заказы по атрибуции WB,
-- только справочно; для распределения фактических списаний не используется).
--
-- Повторная загрузка fullstats обновляет строки по natural key (WB может
-- уточнять статистику за прошедшие дни) — upsert делает CRUD-слой.
--
-- Применяется вручную (конвенция проекта), модель: app/models/wb_advertising.py.

CREATE TABLE IF NOT EXISTS public.wb_ad_product_daily_stats (
    id bigserial NOT NULL,
    tenant_id int4 NOT NULL,
    advert_id int8 NOT NULL,

    stat_date_msk date NOT NULL,               -- days[].date в Europe/Moscow
    stat_month_msk date NOT NULL,              -- первое число месяца stat_date_msk

    app_type int4 NOT NULL,                    -- apps[].appType
    nm_id int8 NOT NULL,                       -- nms[].nmId
    product_name varchar(1000) NULL,           -- nms[].name

    views int8 NOT NULL DEFAULT 0,
    clicks int8 NOT NULL DEFAULT 0,
    atbs int8 NOT NULL DEFAULT 0,              -- добавления в корзину
    orders int8 NOT NULL DEFAULT 0,
    shks int8 NOT NULL DEFAULT 0,              -- заказы (шк)
    canceled int8 NOT NULL DEFAULT 0,

    stat_spend_amount numeric(14, 2) NOT NULL DEFAULT 0,    -- ТОЛЬКО nms[].sum
    attributed_orders_amount numeric(14, 2) NOT NULL DEFAULT 0, -- nms[].sum_price

    cpc numeric(14, 4) NULL,
    ctr numeric(14, 4) NULL,
    cr numeric(14, 4) NULL,

    currency varchar(10) NOT NULL DEFAULT 'RUB',

    raw_payload jsonb NULL,                    -- исходная товарная строка nms[]

    synced_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT wb_ad_product_daily_stats_pkey PRIMARY KEY (id),
    CONSTRAINT wb_ad_product_daily_stats_tenant_id_fkey FOREIGN KEY (tenant_id)
        REFERENCES tenants(id) ON DELETE CASCADE,
    CONSTRAINT uq_wb_ad_product_daily_stats_natural_key
        UNIQUE (tenant_id, advert_id, stat_date_msk, app_type, nm_id),
    CONSTRAINT ck_wb_ad_product_daily_stats_spend_nonneg CHECK (stat_spend_amount >= 0),
    CONSTRAINT ck_wb_ad_product_daily_stats_attributed_nonneg CHECK (attributed_orders_amount >= 0)
);

CREATE INDEX IF NOT EXISTS ix_wb_ad_product_daily_stats_tenant_advert_date ON public.wb_ad_product_daily_stats
    USING btree (tenant_id, advert_id, stat_date_msk);
CREATE INDEX IF NOT EXISTS ix_wb_ad_product_daily_stats_tenant_nm_date ON public.wb_ad_product_daily_stats
    USING btree (tenant_id, nm_id, stat_date_msk);
CREATE INDEX IF NOT EXISTS ix_wb_ad_product_daily_stats_tenant_month_nm ON public.wb_ad_product_daily_stats
    USING btree (tenant_id, stat_month_msk, nm_id);

ALTER TABLE public.wb_ad_product_daily_stats OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.wb_ad_product_daily_stats TO marketfinance_user;
