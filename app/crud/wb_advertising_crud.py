# crud/wb_advertising_crud.py
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, literal_column
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.wb_advertising import WBAdExpenseOperation, WBAdProductDailyStat

MSK = ZoneInfo("Europe/Moscow")

# Размер пакета для bulk-upsert fullstats
FULLSTATS_BATCH_SIZE = 500


def compute_source_hash(record: dict) -> str:
    """sha256 канонического JSON записи WB (сортировка ключей, без пробелов).

    Идемпотентность /adv/v1/upd: одинаковая исходная запись WB даёт одинаковый
    хэш → повторный импорт не создаёт дубль (UNIQUE tenant_id + source_hash).
    """
    canonical = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def parse_upd_time(raw_time: Any) -> Tuple[datetime, date, date]:
    """updTime → (aware-datetime, дата в МСК, первое число месяца в МСК).

    Расход относится к календарному дню/месяцу updTime в Europe/Moscow.
    Наивное время трактуется как МСК (WB отдаёт время с offset).
    """
    if isinstance(raw_time, datetime):
        dt = raw_time
    else:
        dt = datetime.fromisoformat(str(raw_time))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    dt_msk = dt.astimezone(MSK)
    return dt_msk, dt_msk.date(), dt_msk.date().replace(day=1)


def parse_decimal(value: Any) -> Optional[Decimal]:
    """Строку/число → Decimal (деньги — только Decimal, никаких float)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def create_or_get_expense_operation(
    db: Session,
    tenant_id: int,
    upd_record: dict,
    synced_at: Optional[datetime] = None,
) -> Tuple[WBAdExpenseOperation, bool]:
    """Создать операцию списания /adv/v1/upd, либо вернуть существующую.

    Возвращает (объект, создана_ли). Не коммитит — управление транзакцией
    у вызывающего (сервис коммитит пакетами по дням).
    """
    source_hash = compute_source_hash(upd_record)
    existing = db.execute(
        select(WBAdExpenseOperation).where(
            WBAdExpenseOperation.tenant_id == tenant_id,
            WBAdExpenseOperation.source_hash == source_hash,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    expense_dt, expense_day, expense_month = parse_upd_time(upd_record.get('updTime'))
    amount = parse_decimal(upd_record.get('updSum'))
    if amount is None:
        raise ValueError(f"Некорректный updSum в записи /adv/v1/upd: {upd_record.get('updSum')!r}")

    operation = WBAdExpenseOperation(
        tenant_id=tenant_id,
        advert_id=int(upd_record['advertId']),
        expense_datetime=expense_dt,
        expense_date_msk=expense_day,
        expense_month_msk=expense_month,
        expense_amount=amount,
        currency=str(upd_record.get('currency') or 'RUB')[:10],
        wb_upd_num=upd_record.get('updNum'),
        campaign_name=str(upd_record['campName'])[:500] if upd_record.get('campName') else None,
        payment_type=str(upd_record['paymentType'])[:100] if upd_record.get('paymentType') else None,
        advert_type=upd_record.get('advertType'),
        advert_status=upd_record.get('advertStatus'),
        source_hash=source_hash,
        raw_payload=upd_record,
        synced_at=synced_at or datetime.now(MSK),
    )
    db.add(operation)
    db.flush()
    return operation, True


def bulk_ingest_expense_operations(
    db: Session,
    tenant_id: int,
    upd_records: List[dict],
    synced_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Пакетная загрузка записей /adv/v1/upd (идемпотентно, по source_hash).

    Существующие хэши выбираются ОДНИМ запросом, новые строки добавляются
    одним flush — построчных коммитов нет.
    """
    if not upd_records:
        return {
            'created_count': 0,
            'existing_count': 0,
            'total_input_amount': Decimal('0'),
            'total_created_amount': Decimal('0'),
        }

    hashes = [compute_source_hash(r) for r in upd_records]
    existing_hashes = set(
        db.execute(
            select(WBAdExpenseOperation.source_hash).where(
                WBAdExpenseOperation.tenant_id == tenant_id,
                WBAdExpenseOperation.source_hash.in_(hashes),
            )
        ).scalars()
    )

    created_count = 0
    total_created_amount = Decimal('0')
    total_input_amount = Decimal('0')

    for record, source_hash in zip(upd_records, hashes):
        amount = parse_decimal(record.get('updSum')) or Decimal('0')
        total_input_amount += amount
        if source_hash in existing_hashes:
            continue

        operation, was_created = create_or_get_expense_operation(db, tenant_id, record, synced_at)
        if was_created:
            created_count += 1
            total_created_amount += operation.expense_amount
            existing_hashes.add(source_hash)

    return {
        'created_count': created_count,
        'existing_count': len(upd_records) - created_count,
        'total_input_amount': total_input_amount,
        'total_created_amount': total_created_amount,
    }


def bulk_upsert_product_daily_stats(
    db: Session,
    tenant_id: int,
    normalized_records: List[dict],
    synced_at: Optional[datetime] = None,
    batch_size: int = FULLSTATS_BATCH_SIZE,
) -> Dict[str, Any]:
    """Пакетный upsert дневной статистики fullstats по natural key.

    Конфликтный ключ: (tenant_id, advert_id, stat_date_msk, app_type, nm_id).
    Обновляются метрики, product_name, raw_payload, synced_at, updated_at —
    WB уточняет статистику прошедших дней, поэтому повторный импорт обновляет
    строки, не создавая дублей.

    inserted/updated различаются по системной колонке xmax (0 = вставка) в
    RETURNING. Коммит остаётся за вызывающим.
    """
    if not normalized_records:
        return {'inserted_count': 0, 'updated_count': 0, 'total_stat_spend': Decimal('0')}

    now = synced_at or datetime.now(MSK)
    inserted = 0
    updated = 0
    total_stat_spend = Decimal('0')

    update_cols = (
        'product_name', 'views', 'clicks', 'atbs', 'orders', 'shks', 'canceled',
        'stat_spend_amount', 'attributed_orders_amount', 'cpc', 'ctr', 'cr',
        'raw_payload', 'synced_at',
    )

    for start in range(0, len(normalized_records), batch_size):
        batch = normalized_records[start:start + batch_size]
        values = []
        for rec in batch:
            total_stat_spend += rec.get('stat_spend_amount') or Decimal('0')
            values.append({
                'tenant_id': tenant_id,
                'advert_id': rec['advert_id'],
                'stat_date_msk': rec['stat_date_msk'],
                'stat_month_msk': rec['stat_month_msk'],
                'app_type': rec['app_type'],
                'nm_id': rec['nm_id'],
                'product_name': rec.get('product_name'),
                'views': rec.get('views', 0),
                'clicks': rec.get('clicks', 0),
                'atbs': rec.get('atbs', 0),
                'orders': rec.get('orders', 0),
                'shks': rec.get('shks', 0),
                'canceled': rec.get('canceled', 0),
                'stat_spend_amount': rec.get('stat_spend_amount') or Decimal('0'),
                'attributed_orders_amount': rec.get('attributed_orders_amount') or Decimal('0'),
                'cpc': rec.get('cpc'),
                'ctr': rec.get('ctr'),
                'cr': rec.get('cr'),
                'currency': rec.get('currency', 'RUB'),
                'raw_payload': rec.get('raw_payload'),
                'synced_at': now,
            })

        stmt = pg_insert(WBAdProductDailyStat).values(values)
        # В SET ссылаемся на EXCLUDED (предлагаемые новые значения):
        # ссылка на имя таблицы в ON CONFLICT DO UPDATE означает СТАРОЕ
        # значение строки — обновление превратилось бы в no-op.
        stmt = stmt.on_conflict_do_update(
            constraint='uq_wb_ad_product_daily_stats_natural_key',
            set_={col: stmt.excluded[col] for col in update_cols}
            | {'updated_at': func.now()},
        ).returning(literal_column('(xmax = 0)').label('inserted'))
        rows = db.execute(stmt).scalars().all()
        inserted += sum(1 for flag in rows if flag in ('true', 't', True))
        updated += sum(1 for flag in rows if flag not in ('true', 't', True))

    return {
        'inserted_count': inserted,
        'updated_count': updated,
        'total_stat_spend': total_stat_spend,
    }
