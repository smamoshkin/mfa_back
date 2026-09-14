# scripts/rehash_ad_source_hashes.py
"""
Разовый перехэш source_hash в wb_ad_expense_operations под стабильную
идентичность траты (advert_id + updTime + upd_sum + currency, БЕЗ updNum).

Когда выполнять: ПОСЛЕ деплоя бэка с фиксом идентичности (v1.6.1+) и ПОСЛЕ
дедупликации db/scripts/05_dedup_wb_ad_expense_operations.sql, ДО следующего
рекламного синка. Без перехэша новые загрузки не "узнают" старые строки
(хэши считались по другому алгоритму) и логический уник-индекс уронит синк.

Запуск на сервере (stdin-pipe, файл не обязан быть в образе):
    docker compose exec -T backend python - < scripts/rehash_ad_source_hashes.py

Порядок деплоя БД-части см. AGENTS.md / db/scripts/05_*.sql.
"""
import hashlib
import time
from decimal import Decimal, ROUND_HALF_UP
from datetime import timezone

from sqlalchemy import bindparam, text

from app.database.database import SessionLocal


def charge_identity(advert_id: int, expense_dt, upd_sum: Decimal, currency: str) -> str:
    upd_utc = expense_dt.astimezone(timezone.utc).isoformat()
    upd_sum_str = str(Decimal(upd_sum).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    return f"{advert_id}|{upd_utc}|{upd_sum_str}|{currency}"


def stable_hash(advert_id: int, expense_dt, upd_sum: Decimal, currency: str) -> str:
    import hashlib
    return hashlib.sha256(
        charge_identity(advert_id, expense_dt, upd_sum, currency).encode('utf-8')
    ).hexdigest()


def main():
    db = SessionLocal()
    db.execute(text("SET statement_timeout = '30min'"))
    try:
        rows = db.execute(text(
            "SELECT id, advert_id, expense_datetime, expense_amount, currency "
            "FROM wb_ad_expense_operations"
        )).fetchall()
        print(f"строк к перехэшу: {len(rows)}", flush=True)

        updates = []
        for r in rows:
            h = stable_hash(r.advert_id, r.expense_datetime, r.expense_amount, r.currency)
            updates.append({"id": r.id, "h": h})

        stmt = text(
            "UPDATE wb_ad_expense_operations SET source_hash = :h WHERE id = :id"
        ).bindparams(bindparam("h"), bindparam("id"))
        db.execute(stmt, updates)
        db.commit()

        print(f"✅ перехэшировано {len(updates)} строк", flush=True)
    except Exception as e:
        db.rollback()
        print(f"❌ перехэш упал: {e}", flush=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
