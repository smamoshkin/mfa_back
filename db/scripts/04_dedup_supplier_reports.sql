-- Дедупликация supplier_reports перед уник-индексом (TODO №2).
--
-- ⚠️ Выполнять ТОЛЬКО если проверка из 02_unique_supplier_reports_rrd.sql
--    нашла дубли (запрос в шапке того файла). Если дублей 0 — файл можно
--    не выполнять.
--
-- Что делает:
--   1. Страховочная копия ВСЕХ строк дубль-групп в таблицу
--      supplier_reports_dupes_backup (не удалять её!).
--   2. В каждой группе (tenant_id, rrd_id) остаётся строка с максимальным id
--      (= загруженная последней, самое свежее состояние WB), остальные
--      удаляются.
--
-- Эффект для аналитики: цифры за задвоенные периоды СНИЗЯТСЯ до корректных
-- (дубли двойно учитывались в агрегатах).
--
-- На тестовой БД выполнено 07.09.2026: 3359 групп удалено, бэкап сохранён.
--
-- После выполнения продолжить: 03_supplier_reports_extract_fields.sql и
-- дальнейшие шаги чек-листа деплоя. Таблицу supplier_reports_agg пересчитать
-- (recompute_analytics_task), т.к. старые агрегаты считались по дублям.

-- Страховочная копия
CREATE TABLE public.supplier_reports_dupes_backup AS
SELECT s.*
FROM supplier_reports s
JOIN (
    SELECT tenant_id, rrd_id
    FROM supplier_reports
    WHERE rrd_id IS NOT NULL
    GROUP BY 1, 2 HAVING count(*) > 1
) d ON s.tenant_id = d.tenant_id AND s.rrd_id = d.rrd_id;

-- Дедупликация
DELETE FROM supplier_reports s
USING (
    SELECT tenant_id, rrd_id, max(id) AS keep_id
    FROM supplier_reports
    WHERE rrd_id IS NOT NULL
    GROUP BY 1, 2 HAVING count(*) > 1
) d
WHERE s.tenant_id = d.tenant_id AND s.rrd_id = d.rrd_id AND s.id <> d.keep_id;
