-- 01_create_supplier_reports_agg_mv.sql
-- ============================================================================
-- Подневная агрегированная материализованная view.
--
-- Физически хранит результат агрегации supplier_reports по измерению
-- (tenant_id, period_day, sku). Заменяет чтение из обычной view
-- supplier_reports_aggregated_v на путях аналитики (AnalyticsService).
--
-- Логика расчёта period_month (CASE с date_from/date_to) и всех агрегатов
-- перенесена из db/views/supplier_reports_aggregated_v.sql БЕЗ ИЗМЕНЕНИЙ —
-- семантика отчётов сохраняется.
--
-- ВАЖНО про таймзону (почему здесь ::timestamp, а не ::timestamp with time zone):
--   sr.sale_dt имеет тип date. В оригинальной view написано
--   date_trunc('month', sr.sale_dt::timestamp with time zone). Приведение
--   date -> timestamptz идёт ПО ТАЙМЗОНЕ СЕССИИ: в UTC-сессии date '2026-04-01'
--   превращается в '2026-04-01 00:00+00', в MSK-сессии — в '2026-04-01 00:00+03'.
--   Для обычной view это незаметно (пересчитывается при каждом селекте в зоне
--   читающего). Для MATERIALIZED VIEW результат ЗАМЕРЗАЕТ в зоне создания/REFRESH:
--   будучи посчитанной в MSK и прочитанной бэкендом в UTC, запись 1 апреля
--   превращается в '2026-03-31 21:00+00' и отсекается фильтром >= '2026-04-01'.
--   Решение: приводить к timestamp WITHOUT time zone — у него нет зоны, и
--   date '2026-04-01' всегда даёт '2026-04-01 00:00:00' в любой сессии.
--   Результаты period_* дополнительно кастятся к date.
--
-- WITH DATA — мат.view заполняется сразу при создании (первый «рефреш» идёт
-- внутри CREATE MATERIALIZED VIEW).
--
-- Уникальный индекс обязателен: без него невозможен
-- REFRESH MATERIALIZED VIEW CONCURRENTLY (см. sync_service.py).
-- ============================================================================

-- На случай повторного применения: сначала drop. CASCADE — потому что на эту
-- мат.view ссылается product_margins_mv (создаётся файлом 02); без CASCADE
-- повторный прогон упадёт с "cannot drop ... because other objects depend on it".
-- Обе мат.view пересоздаются скриптами сразу после, так что CASCADE безопасен.
DROP MATERIALIZED VIEW IF EXISTS public.supplier_reports_agg_mv CASCADE;

CREATE MATERIALIZED VIEW public.supplier_reports_agg_mv
AS
SELECT sr.tenant_id,
    (date_trunc('day'::text,   sr.sale_dt::timestamp))::date  AS period_day,
    (date_trunc('week'::text,  sr.sale_dt::timestamp))::date  AS period_week,
    (CASE
            WHEN date_trunc('month'::text, sr.sale_dt::timestamp) < date_trunc('month'::text, sr.date_from::timestamp) OR date_trunc('month'::text, sr.sale_dt::timestamp) > date_trunc('month'::text, sr.date_to::timestamp) THEN date_trunc('month'::text, sr.date_to::timestamp)
            ELSE date_trunc('month'::text, sr.sale_dt::timestamp)
        END)::date  AS period_month,
    (date_trunc('quarter'::text, sr.sale_dt::timestamp))::date AS period_quarter,
    (date_trunc('year'::text,   sr.sale_dt::timestamp))::date  AS period_year,
    p.name AS product_name,
    sr.sku,
    sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Продажа'::text THEN 0
            ELSE sr.quantity
        END) AS quantity_sold,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.retail_amount
            ELSE 0::numeric
        END) AS revenue,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.amount_for_pay
            ELSE 0::numeric
        END) AS seller_payout,
    max(sr.retail_price) AS retail_price_max,
    sum(sr.storage_fee) AS storage_fee,
    sum(
        CASE
            WHEN sr.bonus_type_name ~~* '%джем%'::text OR sr.bonus_type_name ~~* '%dzhem%'::text THEN 0::numeric
            ELSE sr.deduction
        END) AS regular_deduction,
    sum(
        CASE
            WHEN sr.bonus_type_name ~~* '%джем%'::text OR sr.bonus_type_name ~~* '%dzhem%'::text THEN sr.deduction
            ELSE 0::numeric
        END) AS dzhem_deduction,
    sum(sr.delivery_rub) AS delivery_rub,
    sum(sr.penalty) AS penalty,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Платная приемка'::text THEN sr.acceptance
            ELSE 0::numeric
        END) AS acceptance,
    sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Возврат'::text THEN 0
            ELSE sr.quantity
        END) AS return_quantity,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Возврат'::text THEN sr.retail_amount
            ELSE 0::numeric
        END) AS return_revenue,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.retail_amount * tr.tax_rate / 100::numeric
            ELSE 0::numeric
        END) AS tax,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.amount_for_pay - sr.retail_amount * tr.tax_rate / 100::numeric
            ELSE 0::numeric
        END) AS payout_after_tax,
    max(COALESCE(pc.cost, 0::numeric)) AS cost_per_unit,
    sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Продажа'::text THEN 0
            ELSE sr.quantity
        END)::numeric * max(COALESCE(pc.cost, 0::numeric)) AS total_cost,
    sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Продажа'::text THEN sr.amount_for_pay - sr.retail_amount * tr.tax_rate / 100::numeric
            ELSE 0::numeric
        END) - sum(
        CASE
            WHEN sr.sku::text = ''::text OR sr.sku IS NULL THEN 0
            WHEN sr.doc_type_name::text <> 'Продажа'::text THEN 0
            ELSE sr.quantity
        END)::numeric * max(COALESCE(pc.cost, 0::numeric)) - sum(sr.delivery_rub) - sum(sr.penalty) - sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Платная приемка'::text THEN sr.acceptance
            ELSE 0::numeric
        END) - sum(
        CASE
            WHEN sr.supplier_oper_name::text = 'Возврат'::text THEN sr.retail_amount
            ELSE 0::numeric
        END) AS margin
   FROM supplier_reports sr
     LEFT JOIN tax_rates tr ON tr.tenant_id = sr.tenant_id AND sr.sale_dt >= tr.start_date AND sr.sale_dt <= COALESCE(tr.end_date, '9999-01-01'::date)
     LEFT JOIN products p ON p.sku::text = sr.sku::text AND p.tenant_id = sr.tenant_id
     LEFT JOIN LATERAL ( SELECT pc_1.cost
           FROM product_costs pc_1
          WHERE pc_1.product_id = p.id AND pc_1.start_date <= COALESCE(sr.sale_dt::timestamp, CURRENT_DATE::timestamp) AND (pc_1.end_date IS NULL OR pc_1.end_date >= COALESCE(sr.sale_dt::timestamp, CURRENT_DATE::timestamp))
          ORDER BY pc_1.start_date DESC
         LIMIT 1) pc ON true
  WHERE sr.sku::text <> ''::text AND sr.sku IS NOT NULL
  GROUP BY sr.tenant_id,
           (date_trunc('day'::text, sr.sale_dt::timestamp)),
           (date_trunc('week'::text, sr.sale_dt::timestamp)),
           (CASE
                WHEN date_trunc('month'::text, sr.sale_dt::timestamp) < date_trunc('month'::text, sr.date_from::timestamp) OR date_trunc('month'::text, sr.sale_dt::timestamp) > date_trunc('month'::text, sr.date_to::timestamp) THEN date_trunc('month'::text, sr.date_to::timestamp)
                ELSE date_trunc('month'::text, sr.sale_dt::timestamp)
           END),
           (date_trunc('quarter'::text, sr.sale_dt::timestamp)),
           (date_trunc('year'::text, sr.sale_dt::timestamp)),
           p.name, sr.sku
WITH DATA;

-- Уникальный индекс: обязателен для REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- ВАЖНО: ключ — (tenant_id, period_day, period_month, sku), а НЕ трёхколоночный.
-- period_month считается через CASE: корректировка с sale_dt, попавшим за пределы
-- окна отчёта WB [date_from; date_to], «прицепляется» к месяцу date_to. Из-за
-- этого один и тот же (tenant_id, period_day, sku) может оказаться в двух разных
-- period_month одновременно (проверено на реальных данных: 2 таких группы).
-- period_month входит в ключ, поэтому уникальность по построению совпадает с
-- GROUP BY view и гарантирует 0 дублей.
CREATE UNIQUE INDEX supplier_reports_agg_mv_uq
    ON public.supplier_reports_agg_mv (tenant_id, period_day, period_month, sku);

-- Permissions — аналогично существующим view.
ALTER TABLE public.supplier_reports_agg_mv OWNER TO marketfinance_user;
GRANT ALL ON TABLE public.supplier_reports_agg_mv TO marketfinance_user;
