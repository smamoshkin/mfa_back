-- Дедупликация wb_ad_expense_operations (фикс 15.09.2026): до перехода на
-- стабильную идентичность траты одна и та же трата записывалась дважды,
-- когда WB возвращал её с разным updNum (0 -> номер УПД).
--
-- Идентичность траты: (tenant_id, advert_id, expense_datetime, expense_amount).
-- В каждой дубли-группе остаётся последняя загруженная строка (max id).
--
-- ⚠️ Выполнять ВМЕСТЕ с rehash'ом source_hash существующих строк
--    (python, см. чек-лист деплоя): до rehash'а новые загрузки не увидят
--    старые строки по новым хэшам.
--
-- НА ТЕСТОВОЙ БД ВЫПОЛНЕНО 15.09.2026.

-- 1. Страховочная копия дубль-строк
CREATE TABLE public.wb_ad_expense_ops_dupes_backup AS
SELECT s.*
FROM wb_ad_expense_operations s
JOIN (
    SELECT tenant_id, advert_id, expense_datetime, expense_amount
    FROM wb_ad_expense_operations
    GROUP BY 1, 2, 3, 4 HAVING count(*) > 1
) d ON s.tenant_id = d.tenant_id AND s.advert_id = d.advert_id
   AND s.expense_datetime = d.expense_datetime AND s.expense_amount = d.expense_amount;

-- 2. Дедупликация
DELETE FROM wb_ad_expense_operations s
USING (
    SELECT tenant_id, advert_id, expense_datetime, expense_amount, max(id) AS keep_id
    FROM wb_ad_expense_operations
    GROUP BY 1, 2, 3, 4 HAVING count(*) > 1
) d
WHERE s.tenant_id = d.tenant_id AND s.advert_id = d.advert_id
  AND s.expense_datetime = d.expense_datetime AND s.expense_amount = d.expense_amount
  AND s.id <> d.keep_id;

-- 3. Логический уник-индекс траты (страховка от повторения кейса)
CREATE UNIQUE INDEX IF NOT EXISTS uq_wb_ad_expense_ops_charge
    ON public.wb_ad_expense_operations (tenant_id, advert_id, expense_datetime, expense_amount);
