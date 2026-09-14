-- Уникальный индекс идемпотентной загрузки (TODO №2): одна строка WB-отчёта
-- = один (tenant_id, rrd_id). Повторная загрузка того же периода обновляет
-- существующие строки (upsert в supplier_report_crud.bulk_create_reports),
-- а не плодит дубли — WB может править sale_dt и суммы у старых строк.
--
-- ⚠️ ПРИМЕНИТЬ ДО деплоя кода с upsert: без индекса ON CONFLICT упадёт
--    с ошибкой "there is no unique or exclusion constraint matching the
--    ON CONFLICT specification".
--
-- Проверка дублей ПЕРЕД применением (должна вернуть 0 строк):
--   SELECT tenant_id, rrd_id, count(*)
--   FROM supplier_reports
--   WHERE rrd_id IS NOT NULL
--   GROUP BY 1, 2 HAVING count(*) > 1;
-- (на тестовой БД проверено 07.09.2026: 0 дублей)

CREATE UNIQUE INDEX IF NOT EXISTS uq_supplier_reports_tenant_rrd
    ON public.supplier_reports (tenant_id, rrd_id);

ALTER TABLE public.supplier_reports OWNER TO marketfinance_user;
