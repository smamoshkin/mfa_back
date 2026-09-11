# services/wb_advertising_service.py
import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import engine
from app.crud.wb_advertising_crud import (
    bulk_ingest_expense_operations,
    bulk_upsert_product_daily_stats,
    parse_decimal,
)
from app.services.wb_api_client import WBAPIClient

# Отдельный логгер: ошибки рекламной синхронизации не должны смешиваться
# с ошибками финансового потока supplier_reports (см. SyncService).
ad_logger = logging.getLogger("app.wb_advertising")

MSK = ZoneInfo("Europe/Moscow")

# Ключ advisory lock для REFRESH рекламных MV. Произвольная константа:
# уникальна среди pg_advisory_* этой БД, не конфликтует с другими подсистемами.
AD_MV_REFRESH_ADVISORY_LOCK_KEY = 72459103

# Ограничения GET /adv/v3/fullstats (OpenAPI WB): ≤50 кампаний и ≤31 день
# на запрос, лимит ~3 запроса/мин на аккаунт продавца.
FULLSTATS_MAX_CAMPAIGNS_PER_REQUEST = 50
FULLSTATS_MAX_DAYS_PER_REQUEST = 31
FULLSTATS_REQUEST_INTERVAL_SECONDS = 21     # 3 запроса/мин с запасом

# Ограничения GET /adv/v1/upd (OpenAPI WB): период от 1 до 31 дня за запрос,
# лимит 1 запрос/сек (всплеск 5). День расхода определяется по updTime каждой
# записи, а не по границам запроса — качаем окнами, а не посуточно.
UPD_MAX_DAYS_PER_REQUEST = 31
UPD_REQUEST_INTERVAL_SECONDS = 1.5          # 1 запрос/сек с запасом

AD_MV_REFRESH_STATEMENTS = [
    # Порядок строгий: дневная аллокация → месячная сводка → рентабельность
    # (каждая следующая читает из предыдущей).
    "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_wb_ad_actual_expense_by_nm_day",
    "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_wb_ad_actual_expense_by_nm_month",
    "REFRESH MATERIALIZED VIEW CONCURRENTLY product_margins_mv",
]


class WBAdvertisingService:
    """Ингест рекламных данных WB и расчёт фактических расходов по артикулам.

    Фактический расход — списания /adv/v1/upd (updSum, день = updTime в МСК).
    Детализация /adv/v3/fullstats (nms[].sum) используется ТОЛЬКО как веса
    распределения фактической суммы по nmId; атрибуция WB (14-дневное окно,
    sum_price) в расход не превращается.
    """

    # ------------------------------------------------------------------
    # /adv/v1/upd
    # ------------------------------------------------------------------

    def ingest_upd_records(self, db: Session, tenant_id: int, upd_payload: List[dict]) -> Dict[str, Any]:
        """Валидация и пакетная запись ответа /adv/v1/upd.

        Идемпотентно: (tenant_id, source_hash) — повторный запуск не создаёт
        дублей. Возвращает статистику импорта.
        """
        if not isinstance(upd_payload, list):
            raise ValueError("Ожидается список записей /adv/v1/upd")

        # Валидация обязательных полей до записи
        for record in upd_payload:
            if not isinstance(record, dict):
                raise ValueError(f"Запись /adv/v1/upd не является объектом: {record!r}")
            if record.get('advertId') is None:
                raise ValueError(f"Запись /adv/v1/upd без advertId: {record!r}")
            if parse_decimal(record.get('updSum')) is None:
                raise ValueError(f"Запись /adv/v1/upd без корректного updSum: {record!r}")
            if not record.get('updTime'):
                raise ValueError(f"Запись /adv/v1/upd без updTime: {record!r}")

        stats = bulk_ingest_expense_operations(db, tenant_id, upd_payload)
        ad_logger.info(
            f"✅ /adv/v1/upd ingested: created={stats['created_count']}, "
            f"existing={stats['existing_count']}, "
            f"input_amount={stats['total_input_amount']}, "
            f"created_amount={stats['total_created_amount']}"
        )
        return stats

    # ------------------------------------------------------------------
    # /adv/v3/fullstats
    # ------------------------------------------------------------------

    def normalize_fullstats_payload(self, tenant_id: int, fullstats_payload: List[dict]) -> List[dict]:
        """Развёртка campaigns → days → apps → nms в плоские нормализованные строки.

        - день приводится к Europe/Moscow;
        - stat_spend_amount = ТОЛЬКО nms[].sum (days[].sum и apps[].sum в
          товарный расход не превращаются — двойной учёт);
        - attributed_orders_amount = nms[].sum_price (справочно);
        - raw_payload — исходная товарная строка nms[].
        """
        if isinstance(fullstats_payload, dict):
            # Некоторые версии WB оборачивают ответ; принимаем оба варианта
            fullstats_payload = fullstats_payload.get('campaigns', [])

        normalized: List[dict] = []
        for campaign in fullstats_payload or []:
            if not isinstance(campaign, dict):
                continue
            advert_id = campaign.get('advertId')
            if advert_id is None:
                continue
            for day_item in campaign.get('days') or []:
                stat_day = self._parse_fullstats_day(day_item.get('date'))
                if stat_day is None:
                    continue
                stat_month = stat_day.replace(day=1)
                for app_item in day_item.get('apps') or []:
                    app_type = app_item.get('appType')
                    if app_type is None:
                        continue
                    for nm_item in app_item.get('nms') or []:
                        nm_id = nm_item.get('nmId')
                        if nm_id is None:
                            continue
                        normalized.append({
                            'advert_id': int(advert_id),
                            'stat_date_msk': stat_day,
                            'stat_month_msk': stat_month,
                            'app_type': int(app_type),
                            'nm_id': int(nm_id),
                            'product_name': nm_item.get('name'),
                            'views': int(nm_item.get('views') or 0),
                            'clicks': int(nm_item.get('clicks') or 0),
                            'atbs': int(nm_item.get('atbs') or 0),
                            'orders': int(nm_item.get('orders') or 0),
                            'shks': int(nm_item.get('shks') or 0),
                            'canceled': int(nm_item.get('canceled') or 0),
                            'stat_spend_amount': parse_decimal(nm_item.get('sum')) or Decimal('0'),
                            'attributed_orders_amount': parse_decimal(nm_item.get('sum_price')) or Decimal('0'),
                            'cpc': parse_decimal(nm_item.get('cpc')),
                            'ctr': parse_decimal(nm_item.get('ctr')),
                            'cr': parse_decimal(nm_item.get('cr')),
                            'currency': 'RUB',  # реклама WB — RUB
                            'raw_payload': nm_item,
                        })
        return normalized

    @staticmethod
    def _parse_fullstats_day(raw_date: Any) -> Optional[date]:
        """days[].date ('2026-09-05' либо datetime с offset) → дата в МСК."""
        if raw_date is None:
            return None
        raw = str(raw_date).strip()
        try:
            if 'T' in raw or ' ' in raw:
                dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=MSK)
                return dt.astimezone(MSK).date()
            return date.fromisoformat(raw[:10])
        except ValueError:
            ad_logger.warning(f"Не удалось разобрать дату fullstats: {raw_date!r}")
            return None

    def ingest_fullstats_payload(self, db: Session, tenant_id: int, fullstats_payload: List[dict]) -> Dict[str, Any]:
        """Нормализация + bulk upsert ответа /adv/v3/fullstats."""
        normalized = self.normalize_fullstats_payload(tenant_id, fullstats_payload)

        campaigns = {rec['advert_id'] for rec in normalized}
        days = {rec['stat_date_msk'] for rec in normalized}

        stats = bulk_upsert_product_daily_stats(db, tenant_id, normalized)
        result = {
            'campaigns_count': len(campaigns),
            'days_count': len(days),
            'nm_rows_count': len(normalized),
            'inserted_count': stats['inserted_count'],
            'updated_count': stats['updated_count'],
            'total_stat_spend': stats['total_stat_spend'],
        }
        ad_logger.info(f"✅ /adv/v3/fullstats ingested: {result}")
        return result

    # ------------------------------------------------------------------
    # REFRESH материализованных view
    # ------------------------------------------------------------------

    def refresh_advertising_materialized_views(self) -> Dict[str, Any]:
        """REFRESH CONCURRENTLY рекламных MV + product_margins_mv.

        Порядок строгий: день → месяц → рентабельность.

        - advisory lock (pg_try_advisory_lock): параллельный refresh не
          запускается, при занятом lock возвращается понятный статус;
        - CONCURRENTLY нельзя в транзакции → отдельное AUTOCOMMIT-соединение
          (тот же паттерн, что у refresh_analytics_materialized_views).

        Вызывать ТОЛЬКО после успешной загрузки и upd, и fullstats.
        """
        start = time.time()
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                locked = conn.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": AD_MV_REFRESH_ADVISORY_LOCK_KEY},
                ).scalar()
                if not locked:
                    ad_logger.warning("⏭️ Ad MV refresh skipped: another refresh is running (advisory lock busy)")
                    return {'status': 'skipped_busy', 'elapsed_ms': 0}
                try:
                    for stmt in AD_MV_REFRESH_STATEMENTS:
                        conn.execute(text(stmt))
                finally:
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": AD_MV_REFRESH_ADVISORY_LOCK_KEY},
                    )
            elapsed_ms = int((time.time() - start) * 1000)
            ad_logger.info(f"✅ Advertising materialized views refreshed (CONCURRENTLY) in {elapsed_ms}ms")
            return {'status': 'ok', 'elapsed_ms': elapsed_ms}
        except Exception as e:
            elapsed_ms = int((time.time() - start) * 1000)
            ad_logger.error(
                f"❌ Advertising MV refresh failed after {elapsed_ms}ms: {e}. "
                f"Analytics will use previous snapshot until next update."
            )
            return {'status': 'error', 'elapsed_ms': elapsed_ms, 'error': str(e)}

    # ------------------------------------------------------------------
    # Оркестрация daily sync (вызывается из SyncService, fail-safe)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_period_into_windows(date_from: date, date_to: date,
                                   max_days: int = FULLSTATS_MAX_DAYS_PER_REQUEST) -> List[Tuple[date, date]]:
        """Диапазон → список окон не длиннее max_days (для upd и fullstats)."""
        windows = []
        start = date_from
        while start <= date_to:
            end = min(start + timedelta(days=max_days - 1), date_to)
            windows.append((start, end))
            start = end + timedelta(days=1)
        return windows

    async def sync_advertising_for_period(
        self,
        db: Session,
        tenant,
        date_from: date,
        date_to: date,
    ) -> Dict[str, Any]:
        """Рекламная синхронизация за диапазон дат (историческая загрузка).

        1) /adv/v1/upd окнами ≤31 день (лимит метода) → wb_ad_expense_operations.
           День/месяц расхода вычисляется из updTime КАЖДОЙ записи при ингесте,
           поэтому границы окон на привязку к дням не влияют. Идемпотентно,
           коммит по окну — повторный запуск ничего не дублирует.
        2) /adv/v3/fullstats: объединённый список кампаний периода, те же окна
           ≤31 день × чанки ≤50 кампаний, пауза 21с между запросами (лимит
           ~3 запроса/мин) → wb_ad_product_daily_stats (upsert по natural key).
        3) После успешной загрузки — refresh MV (день → месяц → рентабельность).

        При любом сбое refresh НЕ выполняется (частично неуспешная загрузка
        не должна протекать в агрегаты); закоммиченное без проблем
        дозагружается повторным запуском.

        Итого запросов к WB: 1–2 на upd + (окна × чанки) на fullstats —
        например, период в 6 недель = 4 запроса вместо 44 посуточных.
        """
        client = WBAPIClient()
        windows = self._split_period_into_windows(date_from, date_to)
        totals = {
            'windows_processed': 0,
            'upd_requests': 0,
            'upd_created': 0,
            'upd_existing': 0,
            'fullstats_inserted': 0,
            'fullstats_updated': 0,
            'fullstats_requests': 0,
            'total_upd_amount': Decimal('0'),
        }

        # --- 1) списания окнами ----------------------------------------------
        all_advert_ids = set()
        for w_idx, (w_from, w_to) in enumerate(windows):
            if w_idx > 0:
                await asyncio.sleep(UPD_REQUEST_INTERVAL_SECONDS)  # лимит 1 req/сек

            upd_payload = await client.get_adv_upd(tenant.wb_api_key, w_from, w_to)
            upd_stats = self.ingest_upd_records(db, tenant.id, upd_payload)
            db.commit()  # окно закоммичено — повторный запуск идемпотентен

            window_ids = {
                int(r['advertId']) for r in upd_payload
                if isinstance(r, dict) and r.get('advertId') is not None
            }
            all_advert_ids |= window_ids
            totals['windows_processed'] += 1
            totals['upd_requests'] += 1
            totals['upd_created'] += upd_stats['created_count']
            totals['upd_existing'] += upd_stats['existing_count']
            totals['total_upd_amount'] += upd_stats['total_input_amount']
            ad_logger.info(
                f"📅 Ad sync upd {w_from}..{w_to}: created={upd_stats['created_count']}, "
                f"existing={upd_stats['existing_count']}, campaigns={len(window_ids)}"
            )

        # --- 2) детализация окнами × чанками ----------------------------------
        if all_advert_ids:
            sorted_ids = sorted(all_advert_ids)
            id_chunks = [
                sorted_ids[i:i + FULLSTATS_MAX_CAMPAIGNS_PER_REQUEST]
                for i in range(0, len(sorted_ids), FULLSTATS_MAX_CAMPAIGNS_PER_REQUEST)
            ]
            ad_logger.info(
                f"📊 Ad sync fullstats: {len(all_advert_ids)} кампаний, "
                f"{len(id_chunks)} чанков(а) × {len(windows)} окон (≤{FULLSTATS_MAX_DAYS_PER_REQUEST} дн.)"
            )

            first_request = True
            for w_from, w_to in windows:
                for chunk in id_chunks:
                    if not first_request:
                        await asyncio.sleep(FULLSTATS_REQUEST_INTERVAL_SECONDS)
                    first_request = False

                    fullstats_payload = await client.get_adv_fullstats(
                        tenant.wb_api_key, chunk, w_from, w_to
                    )
                    fs_stats = self.ingest_fullstats_payload(db, tenant.id, fullstats_payload)
                    db.commit()

                    totals['fullstats_requests'] += 1
                    totals['fullstats_inserted'] += fs_stats['inserted_count']
                    totals['fullstats_updated'] += fs_stats['updated_count']
                    ad_logger.info(
                        f"📊 fullstats {w_from}..{w_to}, {len(chunk)} кампаний: "
                        f"inserted={fs_stats['inserted_count']}, updated={fs_stats['updated_count']}, "
                        f"nm_rows={fs_stats['nm_rows_count']}"
                    )

        # --- 3) refresh --------------------------------------------------------
        totals['mv_refresh'] = self.refresh_advertising_materialized_views()
        return totals
