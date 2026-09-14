-- Вынос полей из raw_data JSON в реляционный вид + generated period_month
-- (TODO №1, часть «извлечь из raw_data поля, нужные приложению»).
--
-- period_month — GENERATED ALWAYS ... STORED: месяц, к которому относится
-- строка (CASE-логика коррекции WB: sale_dt вне окна отчёта [date_from;
-- date_to] прицепляется к месяцу date_to). Считает БД при любой вставке/
-- обновлении — в т.ч. когда WB правит sale_dt при повторной загрузке.
-- Индекс (tenant_id, period_month) — под пересчёт агрегатов по месяцам.
--
-- nm_id / barcode / subject_name / title — поля, которые приложение читало
-- из raw_data JSON (product_sync_service.extract_unique_products_from_period:
-- nmId, sku, subjectName, title). Заполняются при загрузке (report_mapper)
-- + разовый бэкфилл существующих строк ниже.
--
-- ⚠️ ADD COLUMN ... GENERATED ... STORED переписывает таблицу — выполнять
--    вне часов пиковой записи. Backfill UPDATE — один скан с jsonb-извлечением.

ALTER TABLE public.supplier_reports
    ADD COLUMN IF NOT EXISTS period_month date
        GENERATED ALWAYS AS (
            CASE
                WHEN date_trunc('month', sale_dt::timestamp) < date_trunc('month', date_from::timestamp)
                  OR date_trunc('month', sale_dt::timestamp) > date_trunc('month', date_to::timestamp)
                THEN (date_trunc('month', date_to::timestamp))::date
                ELSE (date_trunc('month', sale_dt::timestamp))::date
            END
        ) STORED;

ALTER TABLE public.supplier_reports ADD COLUMN IF NOT EXISTS nm_id bigint;
ALTER TABLE public.supplier_reports ADD COLUMN IF NOT EXISTS barcode varchar(255);
ALTER TABLE public.supplier_reports ADD COLUMN IF NOT EXISTS subject_name varchar(500);
ALTER TABLE public.supplier_reports ADD COLUMN IF NOT EXISTS title text;

CREATE INDEX IF NOT EXISTS ix_supplier_reports_tenant_pmonth
    ON public.supplier_reports (tenant_id, period_month);

-- Разовый бэкфилл из raw_data (идемпотентно: повторный прогон просто
-- пересчитает те же значения). nmId — с защитой от нечислового мусора.
UPDATE public.supplier_reports
SET nm_id = CASE WHEN raw_data ->> 'nmId' ~ '^[0-9]+$'
                 THEN (raw_data ->> 'nmId')::bigint END,
    barcode = raw_data ->> 'sku',
    subject_name = raw_data ->> 'subjectName',
    title = raw_data ->> 'title'
WHERE raw_data IS NOT NULL;

ALTER TABLE public.supplier_reports OWNER TO marketfinance_user;
