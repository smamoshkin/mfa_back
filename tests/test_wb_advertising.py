# tests/test_wb_advertising.py
"""
Тесты рекламного модуля WB: ингест /adv/v1/upd и /adv/v3/fullstats,
аллокация фактических списаний на nmId (дневная и месячная MV), интеграция
с MV рентабельности product_margins_mv.

Соответствует обязательным кейсам из постановки задачи.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.crud.wb_advertising_crud import (
    bulk_ingest_expense_operations,
    compute_source_hash,
    parse_upd_time,
)
from app.models.wb_advertising import WBAdExpenseOperation, WBAdProductDailyStat
from app.services.wb_advertising_service import WBAdvertisingService

from conftest import refresh_views

D = Decimal


def upd_record(**overrides):
    """Базовая запись /adv/v1/upd (как в постановке)."""
    record = {
        "updTime": "2026-09-05T16:15:00.019395+03:00",
        "campName": "Чб карточки аукцион",
        "paymentType": "Баланс",
        "updNum": 313782565,
        "updSum": 1000,
        "advertId": 26451117,
        "advertType": 9,
        "advertStatus": 9,
        "currency": "RUB",
    }
    record.update(overrides)
    return record


def fullstats_campaign(advert_id, day, apps):
    """Ответ /adv/v3/fullstats для одной кампании и одного дня."""
    return {
        "advertId": advert_id,
        "days": [{"date": day, "apps": apps}],
    }


def nm(nm_id, spend, sum_price="0", name="Товар"):
    return {
        "nmId": nm_id,
        "name": name,
        "views": 100, "clicks": 10, "atbs": 5, "orders": 2,
        "shks": 2, "canceled": 0,
        "sum": spend, "sum_price": sum_price,
        "cpc": 1.5, "ctr": 2.5, "cr": 15.0,
    }


@pytest.fixture
def service():
    return WBAdvertisingService()


# ============================================================================
# 1. /adv/v1/upd: идемпотентность
# ============================================================================

class TestUpdIngest:

    def test_same_payload_creates_no_duplicate(self, db, tenant_factory):
        tenant = tenant_factory()
        payload = [upd_record()]
        stats1 = service_ingest(db, tenant.id, payload)
        stats2 = service_ingest(db, tenant.id, payload)

        assert stats1['created_count'] == 1
        assert stats2['created_count'] == 0
        assert stats2['existing_count'] == 1
        assert db.query(WBAdExpenseOperation).count() == 1

    def test_upd_num_zero_does_not_break_idempotency(self, db, tenant_factory):
        tenant = tenant_factory()
        # Две РАЗНЫЕ записи с updNum = 0 — обе сохраняются (ключ не updNum)
        stats = service_ingest(db, tenant.id, [
            upd_record(updNum=0, updSum=100, updTime="2026-09-05T10:00:00+03:00"),
            upd_record(updNum=0, updSum=200, updTime="2026-09-05T11:00:00+03:00"),
        ])
        assert stats['created_count'] == 2
        # Повтор — дублей нет
        stats2 = service_ingest(db, tenant.id, [
            upd_record(updNum=0, updSum=100, updTime="2026-09-05T10:00:00+03:00"),
            upd_record(updNum=0, updSum=200, updTime="2026-09-05T11:00:00+03:00"),
        ])
        assert stats2['created_count'] == 0
        assert stats2['existing_count'] == 2
        assert db.query(WBAdExpenseOperation).count() == 2

    def test_same_upd_num_in_different_campaigns_no_conflict(self, db, tenant_factory):
        stats = service_ingest(db, tenant_factory().id, [
            upd_record(updNum=313782565, advertId=111),
            upd_record(updNum=313782565, advertId=222),
        ])
        assert stats['created_count'] == 2
        assert db.query(WBAdExpenseOperation).count() == 2

    def test_moscow_date_and_month_computed(self, db):
        # 23:30+02:00 = 00:30 следующего дня по МСК, ещё и смена месяца
        _, day, month = parse_upd_time("2026-08-31T23:30:00+02:00")
        assert day == date(2026, 9, 1)
        assert month == date(2026, 9, 1)

        _, day2, month2 = parse_upd_time("2026-09-05T16:15:00.019395+03:00")
        assert day2 == date(2026, 9, 5)
        assert month2 == date(2026, 9, 1)

    def test_stored_moscow_day(self, db, tenant_factory):
        tenant = tenant_factory()
        service_ingest(db, tenant.id, [upd_record(updTime="2026-08-31T23:30:00+02:00")])
        op = db.query(WBAdExpenseOperation).one()
        assert op.expense_date_msk == date(2026, 9, 1)
        assert op.expense_month_msk == date(2026, 9, 1)
        assert op.expense_amount == D('1000')

    def test_source_hash_stable_and_content_sensitive(self):
        h1 = compute_source_hash(upd_record())
        h2 = compute_source_hash(upd_record())                      # тот же контент
        h3 = compute_source_hash(upd_record(updSum=1001))           # другой контент
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 64


def service_ingest(db, tenant_id, payload):
    return WBAdvertisingService().ingest_upd_records(db, tenant_id, payload)


# ============================================================================
# 2. /adv/v3/fullstats: нормализация и upsert
# ============================================================================

class TestFullstats:

    def test_same_nm_in_multiple_app_types_stored_separately(self, db, tenant_factory):
        payload = [fullstats_campaign(1, "2026-09-05", [
            {"appType": 64, "sum": 9999, "nms": [nm(101, "100.00")]},
            {"appType": 32, "sum": 9999, "nms": [nm(101, "50.00")]},
        ])]
        stats = WBAdvertisingService().ingest_fullstats_payload(db, tenant_factory().id, payload)

        rows = db.query(WBAdProductDailyStat).order_by(WBAdProductDailyStat.app_type).all()
        assert len(rows) == 2
        assert {r.app_type for r in rows} == {64, 32}
        assert stats['inserted_count'] == 2
        # Расход SKU после агрегации = сумма nms[].sum по всем appType
        total = sum(r.stat_spend_amount for r in rows)
        assert total == D('150.00')

    def test_no_double_count_from_days_and_apps_sums(self, db, tenant_factory):
        # days[].sum и apps[].sum больше товарного расхода — единственный
        # товарный расход это nms[].sum
        payload = [fullstats_campaign(1, "2026-09-05", [
            {"appType": 64, "sum": "9999.00", "nms": [nm(101, "1360.79", sum_price="11423")]},
        ])]
        # подложим верхнеуровневый sum в день — нормализация обязана его игнорировать
        payload[0]['days'][0]['sum'] = "9999.00"

        WBAdvertisingService().ingest_fullstats_payload(db, tenant_factory().id, payload)

        row = db.query(WBAdProductDailyStat).one()
        assert row.stat_spend_amount == D('1360.79')
        assert row.attributed_orders_amount == D('11423')

    def test_reimport_updates_without_duplicates(self, db, tenant_factory):
        tenant = tenant_factory()
        svc = WBAdvertisingService()

        stats1 = svc.ingest_fullstats_payload(db, tenant.id, [
            fullstats_campaign(1, "2026-09-05", [{"appType": 64, "nms": [nm(101, "100.00")]}])
        ])
        assert stats1['inserted_count'] == 1

        # WB уточнил статистику: сумма изменилась
        stats2 = svc.ingest_fullstats_payload(db, tenant.id, [
            fullstats_campaign(1, "2026-09-05", [{"appType": 64, "nms": [nm(101, "150.00", name="Новое имя")]}])
        ])
        assert stats2['inserted_count'] == 0
        assert stats2['updated_count'] == 1

        rows = db.query(WBAdProductDailyStat).all()
        assert len(rows) == 1
        assert rows[0].stat_spend_amount == D('150.00')
        assert rows[0].product_name == "Новое имя"

    def test_stat_month_first_day(self, db, tenant_factory):
        WBAdvertisingService().ingest_fullstats_payload(db, tenant_factory().id, [
            fullstats_campaign(1, "2026-09-05", [{"appType": 64, "nms": [nm(101, "10")]}])
        ])
        row = db.query(WBAdProductDailyStat).one()
        assert row.stat_date_msk == date(2026, 9, 5)
        assert row.stat_month_msk == date(2026, 9, 1)


# ============================================================================
# 3. Дневная MV аллокации
# ============================================================================

def load_day(db, tenant_id, upd_records, fullstats, engine):
    """Загрузить списания + детализацию и обновить MV."""
    service_ingest(db, tenant_id, upd_records)
    WBAdvertisingService().ingest_fullstats_payload(db, tenant_id, fullstats)
    db.commit()
    refresh_views(engine)


def day_mv_rows(db, tenant_id, advert_id, day):
    return db.execute(text(
        "SELECT nm_id, actual_expense_amount, fullstats_nm_spend_amount,"
        "       fullstats_total_spend_amount, allocation_weight,"
        "       allocated_actual_expense_amount, reconciliation_delta_amount"
        " FROM mv_wb_ad_actual_expense_by_nm_day"
        " WHERE tenant_id = :t AND advert_id = :a AND expense_date_msk = :d"
        " ORDER BY nm_id"
    ), {"t": tenant_id, "a": advert_id, "d": day}).fetchall()


class TestDayAllocationMV:

    def test_single_paid_nm_gets_exact_actual(self, db, engine, tenant_factory):
        """Кейс из постановки: 262 + 1000 + 823 = 2085.00 при fullstats 2082.67."""
        tenant = tenant_factory()
        load_day(db, tenant.id, [
            upd_record(updSum=262, updTime="2026-09-05T10:00:00+03:00"),
            upd_record(updSum=1000, updTime="2026-09-05T12:00:00+03:00"),
            upd_record(updSum=823, updTime="2026-09-05T16:00:00+03:00"),
        ], [fullstats_campaign(26451117, "2026-09-05", [
            {"appType": 64, "nms": [nm(220707476, "2082.67")]},
        ])], engine)

        rows = day_mv_rows(db, tenant.id, 26451117, date(2026, 9, 5))
        assert len(rows) == 1
        r = rows[0]
        assert r.actual_expense_amount == D('2085.00')
        assert r.allocated_actual_expense_amount == D('2085.00')   # ровно факт
        assert r.reconciliation_delta_amount == D('2.33')

    def test_associated_nm_with_zero_spend_excluded(self, db, engine, tenant_factory):
        tenant = tenant_factory()
        # Ассоциированный артикул: заказы есть (sum_price>0), расхода нет (sum=0)
        load_day(db, tenant.id, [
            upd_record(updSum=1000),
        ], [fullstats_campaign(26451117, "2026-09-05", [
            {"appType": 64, "nms": [
                nm(101, "400.00"),
                nm(999, "0", sum_price="5000"),   # ассоциированный
            ]},
        ])], engine)

        rows = day_mv_rows(db, tenant.id, 26451117, date(2026, 9, 5))
        assert [r.nm_id for r in rows] == [101]                    # 999 отсутствует
        assert rows[0].allocated_actual_expense_amount == D('1000.00')

    def test_proportional_allocation_multiple_nms(self, db, engine, tenant_factory):
        tenant = tenant_factory()
        load_day(db, tenant.id, [
            upd_record(updSum=1000),
        ], [fullstats_campaign(26451117, "2026-09-05", [
            {"appType": 64, "nms": [nm(101, "300.00"), nm(202, "700.00") ]},
        ])], engine)

        rows = day_mv_rows(db, tenant.id, 26451117, date(2026, 9, 5))
        assert rows[0].allocated_actual_expense_amount == D('300.00')
        assert rows[1].allocated_actual_expense_amount == D('700.00')
        assert sum(r.allocated_actual_expense_amount for r in rows) == D('1000.00')

    def test_allocation_sum_equals_actual_across_campaign_days(self, db, engine, tenant_factory):
        """Инвариант по всем кампаниям и дням: сумма аллокаций = сумма факта."""
        tenant = tenant_factory()
        load_day(db, tenant.id, [
            upd_record(updSum="333.33", updTime="2026-09-05T10:00:00+03:00"),
            upd_record(updSum="777.77", updTime="2026-09-06T10:00:00+03:00", advertId=222),
            upd_record(updSum="111.11", updTime="2026-09-06T11:00:00+03:00", advertId=222),
        ], [
            fullstats_campaign(26451117, "2026-09-05", [
                {"appType": 64, "nms": [nm(101, "10.00"), nm(202, "20.00")]}]),
            fullstats_campaign(222, "2026-09-06", [
                {"appType": 64, "nms": [nm(101, "1.00"), nm(202, "2.00"), nm(303, "4.00")]}]),
        ], engine)

        # actual_expense_amount хранится в каждой nm-строке группы (кампания×день)
        # одинаковым значением — факт считаем по ДИСТИНКТНЫМ группам, отдельно
        # от суммы аллокаций по строкам.
        actual_total = db.execute(text(
            "SELECT sum(actual) FROM ("
            "  SELECT max(actual_expense_amount) AS actual"
            "  FROM mv_wb_ad_actual_expense_by_nm_day WHERE tenant_id = :t"
            "  GROUP BY tenant_id, advert_id, expense_date_msk, currency) g"
        ), {"t": tenant.id}).scalar()
        allocated_total = db.execute(text(
            "SELECT sum(allocated_actual_expense_amount)"
            " FROM mv_wb_ad_actual_expense_by_nm_day WHERE tenant_id = :t"
        ), {"t": tenant.id}).scalar()
        assert actual_total == D('1222.21')     # факт по группам кампания×день
        assert allocated_total == D('1222.21')  # сумма аллокаций = факт (инвариант)

    def test_rounding_last_nm_gets_remainder(self, db, engine, tenant_factory):
        """100.00 на три равных артикула: 33.33 + 33.33 + 33.34 (остаток последнему)."""
        tenant = tenant_factory()
        load_day(db, tenant.id, [
            upd_record(updSum=100),
        ], [fullstats_campaign(26451117, "2026-09-05", [
            {"appType": 64, "nms": [nm(11, "10"), nm(22, "10"), nm(33, "10")]},
        ])], engine)

        rows = day_mv_rows(db, tenant.id, 26451117, date(2026, 9, 5))
        allocations = [r.allocated_actual_expense_amount for r in rows]
        assert allocations == [D('33.33'), D('33.33'), D('33.34')]  # последний nmId — остаток
        assert sum(allocations) == D('100.00')

    def test_spend_summed_across_app_types_in_allocation(self, db, engine, tenant_factory):
        """Один nmId в двух appType: веса считаются по сумме nms[].sum."""
        tenant = tenant_factory()
        load_day(db, tenant.id, [
            upd_record(updSum=200),
        ], [fullstats_campaign(26451117, "2026-09-05", [
            {"appType": 64, "nms": [nm(101, "60.00")]},
            {"appType": 32, "nms": [nm(101, "40.00"), nm(202, "100.00")]},
        ])], engine)

        rows = day_mv_rows(db, tenant.id, 26451117, date(2026, 9, 5))
        # 101: (60+40)/(60+40+100) * 200 = 100;  202: 100/200*200 = 100
        assert rows[0].fullstats_nm_spend_amount == D('100.00')
        assert rows[0].allocated_actual_expense_amount == D('100.00')
        assert rows[1].allocated_actual_expense_amount == D('100.00')


# ============================================================================
# 4. Месячная MV
# ============================================================================

class TestMonthMV:

    def test_month_aggregation_counts(self, db, engine, tenant_factory):
        tenant = tenant_factory()
        load_day(db, tenant.id, [
            upd_record(updSum="500", updTime="2026-09-05T10:00:00+03:00"),
            upd_record(updSum="300", updTime="2026-09-06T10:00:00+03:00"),
            upd_record(updSum="200", updTime="2026-09-06T11:00:00+03:00", advertId=222),
        ], [
            fullstats_campaign(26451117, "2026-09-05", [
                {"appType": 64, "nms": [nm(101, "50.00"), nm(202, "50.00")]}]),
            fullstats_campaign(26451117, "2026-09-06", [
                {"appType": 64, "nms": [nm(101, "30.00"), nm(202, "70.00")]}]),
            fullstats_campaign(222, "2026-09-06", [
                {"appType": 64, "nms": [nm(101, "20.00")]}]),
        ], engine)

        rows = db.execute(text(
            "SELECT nm_id, allocated_actual_ad_expense_amount, campaigns_count, advertising_days_count"
            " FROM mv_wb_ad_actual_expense_by_nm_month"
            " WHERE tenant_id = :t AND expense_month_msk = '2026-09-01'"
            " ORDER BY nm_id"
        ), {"t": tenant.id}).fetchall()

        by_nm = {r.nm_id: r for r in rows}
        # 101: 05.09 → 250 (единственный день кампании 1... веса 50/100 и 30/100)
        #   05.09: 500 * 50/100 = 250; 06.09 (кампания 1): 300 * 30/100 = 90; кампания 2: 200 * 100% = 200
        assert by_nm[101].allocated_actual_ad_expense_amount == D('540.00')
        assert by_nm[101].campaigns_count == 2            # кампании 26451117 и 222
        assert by_nm[101].advertising_days_count == 2      # 05.09 и 06.09
        # 202: 500*50/100 + 300*70/100 = 250 + 210
        assert by_nm[202].allocated_actual_ad_expense_amount == D('460.00')
        assert by_nm[202].campaigns_count == 1
        assert by_nm[202].advertising_days_count == 2
        # Итог месяца = факту
        total = sum(r.allocated_actual_ad_expense_amount for r in rows)
        assert total == D('1000.00')


# ============================================================================
# 5. Интеграция с MV рентабельности product_margins_mv
# ============================================================================

def seed_finance(db, tenant, sku, marketplace_sku, sale_dt,
                 quantity=10, retail=1000, payout=800):
    """Товар + запись продажи в supplier_reports."""
    from app.models.product import Product
    from app.models.supplier_report import SupplierReport
    from app.models.tax_rate import TaxRate

    db.add(TaxRate(tenant_id=tenant.id, tax_rate=0, start_date=date(2000, 1, 1)))
    product = Product(
        tenant_id=tenant.id, sku=sku, marketplace_sku=marketplace_sku,
        name=f"Товар {sku}",
    )
    db.add(product)
    db.add(SupplierReport(
        tenant_id=tenant.id,
        realizationreport_id=1,
        rrd_id=abs(hash(sku)) % 10**9,
        date_from=sale_dt.replace(day=1), date_to=sale_dt, sale_dt=sale_dt,
        sku=sku,
        doc_type_name="Продажа", supplier_oper_name="Продажа",
        bonus_type_name="",
        quantity=quantity, retail_amount=retail, amount_for_pay=payout,
        retail_price=retail,
        storage_fee=0, deduction=0, delivery_rub=0, penalty=0, acceptance=0,
    ))
    db.flush()
    return product


def margins_row(db, tenant_id, sku):
    return db.execute(text(
        "SELECT revenue, margin, nm_id, actual_ad_expense_amount, campaigns_count,"
        "       advertising_days_count, factual_drr_percent, margin_after_advertising"
        " FROM product_margins WHERE tenant_id = :t AND sku = :s"
    ), {"t": tenant_id, "s": sku}).fetchone()


class TestMarginsIntegration:

    def test_ad_expense_joined_by_tenant_month_nm(self, db, engine, tenant_factory):
        tenant = tenant_factory()
        seed_finance(db, tenant, "SKU-1", "12345", date(2026, 9, 10))
        db.commit()

        load_day(db, tenant.id, [
            upd_record(updSum=1000, updTime="2026-09-10T12:00:00+03:00"),
        ], [fullstats_campaign(26451117, "2026-09-10", [
            {"appType": 64, "nms": [nm(12345, "500.00")]},
        ])], engine)

        row = margins_row(db, tenant.id, "SKU-1")
        assert row is not None
        assert row.nm_id == 12345
        assert row.actual_ad_expense_amount == D('1000.00')   # единственный nm — весь факт
        assert row.campaigns_count == 1
        assert row.advertising_days_count == 1
        assert row.revenue == D('1000.00')
        # налог 0%, себестоимости нет: margin = payout = 800
        assert row.margin == D('800.00')
        assert row.factual_drr_percent == D('100.00')          # 1000/1000*100
        assert row.margin_after_advertising == D('-200.00')    # 800 - 1000

    def test_no_ads_zero_expense_and_zero_drr(self, db, engine, tenant_factory):
        tenant = tenant_factory()
        seed_finance(db, tenant, "SKU-2", "999", date(2026, 9, 10))
        db.commit()
        refresh_views(engine)

        row = margins_row(db, tenant.id, "SKU-2")
        assert row.actual_ad_expense_amount == D('0.00')
        assert row.campaigns_count == 0
        assert row.factual_drr_percent == D('0.00')            # выручка > 0 → 0, не NULL
        assert row.margin_after_advertising == row.margin

    def test_zero_revenue_drr_is_null(self, db, engine, tenant_factory):
        """Без продаж выручка 0 → factual_drr_percent = NULL (не 0)."""
        from app.models.product import Product
        from app.models.supplier_report import SupplierReport

        tenant = tenant_factory()
        db.add(Product(tenant_id=tenant.id, sku="SKU-3", marketplace_sku="777",
                       name="Только возвраты"))
        # Единственная строка — возврат: revenue = 0
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=2,
            rrd_id=555555, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30),
            sale_dt=date(2026, 9, 15), sku="SKU-3",
            doc_type_name="Возврат", supplier_oper_name="Возврат",
            bonus_type_name="", quantity=1,
            retail_amount=500, amount_for_pay=0,
        ))
        db.commit()
        refresh_views(engine)

        row = margins_row(db, tenant.id, "SKU-3")
        assert row.revenue == 0
        assert row.factual_drr_percent is None

    def test_different_tenants_isolated(self, db, engine, tenant_factory):
        """Расходы одного тенанта не протекают в рентабельность другого."""
        tenant_a, tenant_b = tenant_factory(), tenant_factory()
        seed_finance(db, tenant_a, "SKU-A", "12345", date(2026, 9, 10))
        seed_finance(db, tenant_b, "SKU-B", "12345", date(2026, 9, 10))
        db.commit()

        # Реклама только у тенанта A
        load_day(db, tenant_a.id, [
            upd_record(updSum=500, updTime="2026-09-10T12:00:00+03:00"),
        ], [fullstats_campaign(26451117, "2026-09-10", [
            {"appType": 64, "nms": [nm(12345, "100.00")]},
        ])], engine)

        row_a = margins_row(db, tenant_a.id, "SKU-A")
        row_b = margins_row(db, tenant_b.id, "SKU-B")
        assert row_a.actual_ad_expense_amount == D('500.00')
        assert row_b.actual_ad_expense_amount == D('0.00')


# ============================================================================
# REFRESH через сервис (advisory lock)
# ============================================================================

class TestRefreshService:

    def test_refresh_ok_and_busy_status(self, db, engine, tenant_factory):
        load_day(db, tenant_factory().id, [upd_record(updSum=10)],
                 [fullstats_campaign(1, "2026-09-05", [{"appType": 64, "nms": [nm(1, "5")]}])],
                 engine)

        svc = WBAdvertisingService()
        result = svc.refresh_advertising_materialized_views()
        assert result['status'] == 'ok'

        # Занятый advisory lock → понятный статус, не исключение
        from app.database.database import engine as app_engine
        with app_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("SELECT pg_advisory_lock(72459103)"))
            try:
                busy = svc.refresh_advertising_materialized_views()
                assert busy['status'] == 'skipped_busy'
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(72459103)"))

        ok2 = svc.refresh_advertising_materialized_views()
        assert ok2['status'] == 'ok'


class TestStableChargeIdentity:

    def test_same_charge_different_updnum_is_same_charge(self, db, tenant_factory):
        """Реальный кейс с прода/теста (14.09): WB возвращает одну трату дважды —
        сначала с updNum=0 (УПД не сформирован), затем с реальным номером УПД.
        Это ОДНА трата: вторая запись не должна создавать дубль."""
        tenant = tenant_factory()
        first = upd_record(updNum=0, updSum=2150, updTime="2026-09-12T23:59:59+03:00")
        second = upd_record(updNum=315200384, updSum=2150, updTime="2026-09-12T23:59:59+03:00")
        assert first["updNum"] != second["updNum"]  # различается ТОЛЬКО updNum

        service_ingest(db, tenant.id, [first])
        stats2 = service_ingest(db, tenant.id, [second])

        assert stats2['created_count'] == 0
        assert stats2['existing_count'] == 1
        assert db.query(WBAdExpenseOperation).count() == 1

    def test_in_batch_duplicate_same_charge(self, db, tenant_factory):
        """Дубль ВНУТРИ одного батча тоже схлопывается (keep last)."""
        tenant = tenant_factory()
        stats = service_ingest(db, tenant.id, [
            upd_record(updNum=0, updSum=500, updTime="2026-09-12T10:00:00+03:00"),
            upd_record(updNum=777, updSum=500, updTime="2026-09-12T10:00:00+03:00"),
        ])
        assert stats['created_count'] == 1
        assert db.query(WBAdExpenseOperation).count() == 1

    def test_hash_ignores_updnum(self):
        """updNum не участвует в идентичности; updTime/updSum — участвуют."""
        base = dict(advertId=9, updSum=100, updTime="2026-09-12T10:00:00+03:00")
        h1 = compute_source_hash({"advertId": 9, "updSum": 100, "updTime": "2026-09-12T10:00:00+03:00", "updNum": 0})
        h2 = compute_source_hash({"advertId": 9, "updSum": 100, "updTime": "2026-09-12T10:00:00+03:00", "updNum": 999})
        h3 = compute_source_hash({"advertId": 9, "updSum": 200, "updTime": "2026-09-12T10:00:00+03:00", "updNum": 0})
        h4 = compute_source_hash({"advertId": 9, "updSum": 100, "updTime": "2026-09-13T10:00:00+03:00", "updNum": 0})
        assert h1 == h2                      # updNum не влияет
        assert h1 != h3                      # сумма влияет
        assert h1 != h4                      # время влияет

    def test_different_currency_different_charge(self, db, tenant_factory):
        tenant = tenant_factory()
        stats = service_ingest(db, tenant.id, [
            upd_record(updSum=100, currency="RUB"),
            upd_record(updSum=100, currency="USD"),
        ])
        assert stats['created_count'] == 2
        assert db.query(WBAdExpenseOperation).count() == 2
