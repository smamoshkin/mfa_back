-- 01_mark_existing_verified.sql
-- Разовая миграция при внедрении верификации email:
-- существующим тенантам проставить email_verified=true, чтобы они не
-- оказались заперты (замок действует только на новых регистрациях).
--
-- При необходимости исключить конкретных тенантов — добавьте
--   AND id NOT IN (...)
UPDATE tenants
SET email_verified = true
WHERE email_verified IS DISTINCT FROM true;

-- Проверка:
-- SELECT id, login_email, email_verified FROM tenants ORDER BY id;
