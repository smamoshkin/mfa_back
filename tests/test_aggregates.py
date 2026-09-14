# tests/test_aggregates.py
"""
Тесты перехода с мат.view на таблицы агрегатов (TODO №1 + фундамент №2):
идемпотентный upsert supplier_reports, пересчёт supplier_reports_agg /
product_margins по месяцам, CASE-коррекция месяца.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crud.supplier_report_crud import bulk_create_reports
from app.models.supplier_report import SupplierReport
from app.schemas.supplier_report import SupplierReportCreate

from conftest import refresh_views

D = Decimal


def make_report(rrd_id, sku, sale_dt, quantity=10, retail=1000, payout=800,
                date_from=None, date_to=None, oper="Продажа", tenant_id=1):
    """Запись SupplierReportCreate с дефолтами (продажа).
    tenant_id в схеме обязателен, но bulk_create_reports его перезаписывает."""
    return SupplierReportCreate(
        tenant_id=tenant_id,
        realizationreport_id=1,
        rrd_id=rrd_id,
        date_from=date_from or sale_dt.replace(day=1),
        date_to=date_to or sale_dt,
        sale_dt=sale_dt,
        sku=sku,
        doc_type_name=oper if oper in ("Продажа", "Возврат") else "Продажа",
        supplier_oper_name=oper,
        bonus_type_name="",
        quantity=quantity,
        retail_amount=retail,
        amount_for_pay=payout,
        retail_price=retail,
        storage_fee=0, deduction=0, delivery_rub=0, penalty=0, acceptance=0,
    )


class TestUpsertSupplierReports:

    def test_repeated_rrd_id_updates_without_duplicate(self, db, tenant_factory):
        """Повторная загрузка того же rrd_id: обновляет sale_dt/суммы, дубля нет."""
        tenant = tenant_factory()
        first = make_report(rrd_id=777, sku="SKU-1", sale_dt=date(2026, 9, 5),
                            quantity=10, retail=1000, payout=800)
        bulk_create_reports(db, [first], tenant.id)
        db.commit()

        # WB исправил строку: другая дата продажи и суммы
        second = make_report(rrd_id=777, sku="SKU-1", sale_dt=date(2026, 9, 20),
                             quantity=12, retail=1200, payout=960)
        bulk_create_reports(db, [second], tenant.id)
        db.commit()

        rows = db.execute(text(
            "SELECT sale_dt, quantity, retail_amount FROM supplier_reports "
            "WHERE tenant_id = :t AND rrd_id = 777"
        ), {"t": tenant.id}).fetchall()

        assert len(rows) == 1
        assert rows[0].sale_dt == date(2026, 9, 20)   # sale_dt обновлён
        assert rows[0].quantity == 12
        assert rows[0].retail_amount == D('1200')

    def test_same_rrd_id_different_tenants_no_conflict(self, db, tenant_factory):
        tenant_a, tenant_b = tenant_factory(), tenant_factory()
        bulk_create_reports(db, [make_report(rrd_id=555, sku="SKU-A", sale_dt=date(2026, 9, 5))], tenant_a.id)
        bulk_create_reports(db, [make_report(rrd_id=555, sku="SKU-B", sale_dt=date(2026, 9, 6))], tenant_b.id)
        db.commit()
        assert db.execute(text(
            "SELECT count(*) FROM supplier_reports "
            "WHERE rrd_id = 555 AND tenant_id IN (:a, :b)"
        ), {"a": tenant_a.id, "b": tenant_b.id}).scalar() == 2

    def test_null_rrd_id_rows_always_inserted(self, db, tenant_factory):
        tenant = tenant_factory()
        bulk_create_reports(db, [
            make_report(rrd_id=None, sku="SKU-N", sale_dt=date(2026, 9, 5)),
            make_report(rrd_id=None, sku="SKU-N", sale_dt=date(2026, 9, 6)),
        ], tenant.id)
        db.commit()
        assert db.execute(text(
            "SELECT count(*) FROM supplier_reports WHERE tenant_id = :t", 
        ).bindparams(t=tenant.id)).scalar() == 2


class TestAggMonthCorrection:

    def test_sale_dt_outside_report_window_attaches_to_date_to_month(self, db, engine, tenant_factory):
        """CASE-коррекция: sale_dt < месяца date_from → строка уходит в месяц
        date_to (месяц исправления WB), НЕ в месяц sale_dt."""
        from app.services.aggregates_service import recompute_supplier_agg

        tenant = tenant_factory()
        # sale_dt в июле, но окно отчёта — сентябрь ( WB прислал исправление)
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=3, rrd_id=999,
            date_from=date(2026, 9, 1), date_to=date(2026, 9, 30),
            sale_dt=date(2026, 7, 15), sku="SKU-C",
            doc_type_name="Продажа", supplier_oper_name="Продажа",
            bonus_type_name="", quantity=5, retail_amount=500, amount_for_pay=400,
        ))
        db.commit()

        recompute_supplier_agg(db, tenant.id, months=[date(2026, 9, 1)])

        rows = db.execute(text(
            "SELECT period_month, quantity_sold, revenue FROM supplier_reports_agg "
            "WHERE tenant_id = :t AND sku = 'SKU-C'"
        ), {"t": tenant.id}).fetchall()

        assert len(rows) == 1
        assert rows[0].period_month == date(2026, 9, 1)   # месяц date_to, не июля
        assert rows[0].revenue == D('500')

        # В июле строки быть не должно
        july = db.execute(text(
            "SELECT count(*) FROM supplier_reports_agg "
            "WHERE tenant_id = :t AND sku = 'SKU-C' AND period_month = '2026-07-01'"
        ), {"t": tenant.id}).scalar()
        assert july == 0

    def test_recompute_is_idempotent(self, db, engine, tenant_factory):
        """Двойной пересчёт того же месяца даёт идентичный результат."""
        from app.services.aggregates_service import recompute_supplier_agg

        tenant = tenant_factory()
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=4, rrd_id=1001,
            date_from=date(2026, 8, 1), date_to=date(2026, 8, 31),
            sale_dt=date(2026, 8, 10), sku="SKU-D",
            doc_type_name="Продажа", supplier_oper_name="Продажа",
            bonus_type_name="", quantity=3, retail_amount=300, amount_for_pay=240,
        ))
        db.commit()

        recompute_supplier_agg(db, tenant.id, months=[date(2026, 8, 1)])
        snap1 = db.execute(text(
            "SELECT * FROM supplier_reports_agg WHERE tenant_id = :t"
        ), {"t": tenant.id}).fetchall()

        recompute_supplier_agg(db, tenant.id, months=[date(2026, 8, 1)])
        snap2 = db.execute(text(
            "SELECT * FROM supplier_reports_agg WHERE tenant_id = :t"
        ), {"t": tenant.id}).fetchall()

        assert len(snap1) == len(snap2) == 1
        assert tuple(snap1[0]) == tuple(snap2[0])

    def test_partial_month_recompute_does_not_touch_other_months(self, db, engine, tenant_factory):
        """Пересчёт одного месяца не удаляет соседние."""
        from app.services.aggregates_service import recompute_supplier_agg

        tenant = tenant_factory()
        for i, d in enumerate((date(2026, 8, 10), date(2026, 9, 10))):
            db.add(SupplierReport(
                tenant_id=tenant.id, realizationreport_id=5, rrd_id=2001 + i,
                date_from=d.replace(day=1), date_to=d, sale_dt=d, sku="SKU-E",
                doc_type_name="Продажа", supplier_oper_name="Продажа",
                bonus_type_name="", quantity=1, retail_amount=100, amount_for_pay=80,
            ))
        db.commit()

        # Первый пересчёт заполняет оба месяца, второй — только сентябрь
        recompute_supplier_agg(db, tenant.id, months=[date(2026, 8, 1), date(2026, 9, 1)])
        recompute_supplier_agg(db, tenant.id, months=[date(2026, 9, 1)])

        months = [r[0] for r in db.execute(text(
            "SELECT period_month FROM supplier_reports_agg WHERE tenant_id = :t"
        ), {"t": tenant.id}).fetchall()]
        assert sorted(months) == [date(2026, 8, 1), date(2026, 9, 1)]


class TestMarginsRecomputeWithMonths:

    def test_margins_recompute_with_explicit_months_list(self, db, engine, tenant_factory):
        """Регрессия: recompute_product_margins с ЯВНЫМ списком месяцев (как
        после изменения налоговой ставки). Ловит потерю AND в фильтре месяцев
        (синтаксическая ошибка 'near \"p\"')."""
        from datetime import date as d
        from app.models.product import Product
        from app.models.supplier_report import SupplierReport
        from app.models.tax_rate import TaxRate
        from app.services.aggregates_service import (
            recompute_supplier_agg,
            recompute_product_margins,
        )

        tenant = tenant_factory()
        db.add(TaxRate(tenant_id=tenant.id, tax_rate=0, start_date=d(2000, 1, 1)))
        db.add(Product(tenant_id=tenant.id, sku="SKU-M", marketplace_sku="4242",
                       name="Товар M"))
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=6, rrd_id=3001,
            date_from=d(2026, 9, 1), date_to=d(2026, 9, 30), sale_dt=d(2026, 9, 10),
            sku="SKU-M", doc_type_name="Продажа", supplier_oper_name="Продажа",
            bonus_type_name="", quantity=10, retail_amount=1000, amount_for_pay=800,
            storage_fee=0, deduction=0, delivery_rub=0, penalty=0, acceptance=0,
        ))
        db.commit()

        recompute_supplier_agg(db, tenant.id, months=[d(2026, 9, 1)])
        # ЯВНЫЙ список месяцев — путь из налогового триггера
        rows = recompute_product_margins(db, tenant.id, months=[d(2026, 9, 1)])

        assert rows == 1
        margin_row = db.execute(text(
            "SELECT revenue, margin FROM product_margins "
            "WHERE tenant_id = :t AND sku = 'SKU-M'"
        ), {"t": tenant.id}).fetchone()
        assert margin_row.revenue == D('1000')
        assert margin_row.margin == D('800')


class TestExtractedFields:

    def test_period_month_generated_on_insert_and_update(self, db, tenant_factory):
        """period_month — generated-колонка: БД считает её сама при вставке
        и ПЕРЕСЧИТЫВАЕТ при обновлении sale_dt (WB двигает даты старых строк)."""
        tenant = tenant_factory()
        bulk_create_reports(db, [make_report(rrd_id=801, sku="SKU-P", sale_dt=date(2026, 9, 5))], tenant.id)
        db.commit()

        pm = db.execute(text(
            "SELECT period_month FROM supplier_reports WHERE tenant_id = :t AND rrd_id = 801"
        ), {"t": tenant.id}).scalar()
        assert pm == date(2026, 9, 1)

        # WB сдвинул дату продажи в другой месяц — колонка пересчитывается сама
        bulk_create_reports(db, [make_report(rrd_id=801, sku="SKU-P", sale_dt=date(2026, 10, 7))], tenant.id)
        db.commit()
        pm2 = db.execute(text(
            "SELECT period_month FROM supplier_reports WHERE tenant_id = :t AND rrd_id = 801"
        ), {"t": tenant.id}).scalar()
        assert pm2 == date(2026, 10, 1)

    def test_mapper_extracts_fields_from_raw_data(self):
        """report_mapper вынимает nm_id/barcode/subject_name/title из raw_data."""
        from app.services.report_mapper import ReportMapperService

        raw = {
            "reportId": 1, "rrdId": 42,
            "dateFrom": "2026-09-01", "dateTo": "2026-09-30",
            "saleDt": "2026-09-10",
            "vendorCode": "ART-1", "nmId": 123456,
            "sku": "2000512345678", "subjectName": "Развивающие карточки",
            "title": "Карточки домана",
            "docTypeName": "Продажа", "sellerOperName": "Продажа",
            "bonusTypeName": "",
        }
        report = ReportMapperService().map_wb_report_to_model(raw, tenant_id=1)
        assert report.nm_id == 123456
        assert report.barcode == "2000512345678"
        assert report.subject_name == "Развивающие карточки"
        assert report.title == "Карточки домана"

    def test_mapper_nm_id_garbage_is_none(self):
        from app.services.report_mapper import ReportMapperService

        raw = {"rrdId": 43, "dateFrom": "2026-09-01", "dateTo": "2026-09-30",
               "saleDt": "2026-09-10", "vendorCode": "ART-2",
               "nmId": "не-число", "docTypeName": "Продажа",
               "sellerOperName": "Продажа", "bonusTypeName": ""}
        report = ReportMapperService().map_wb_report_to_model(raw, tenant_id=1)
        assert report.nm_id is None

    def test_extract_unique_products_reads_columns(self, db, engine, tenant_factory):
        """extract_unique_products_from_period читает вынесенные колонки."""
        from app.services.product_sync_service import ProductSyncService

        tenant = tenant_factory()
        # Две строки одного sku: последняя по sale_dt — источник карточки
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=7, rrd_id=401,
            date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), sale_dt=date(2026, 9, 5),
            sku="SKU-U", doc_type_name="Продажа", supplier_oper_name="Продажа",
            bonus_type_name="", quantity=1,
            nm_id=111, barcode="1111222233330", subject_name="Категория А", title="Старое имя",
        ))
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=7, rrd_id=402,
            date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), sale_dt=date(2026, 9, 20),
            sku="SKU-U", doc_type_name="Продажа", supplier_oper_name="Продажа",
            bonus_type_name="", quantity=1,
            nm_id=222, barcode="2222333344440", subject_name="Категория Б", title="Новое имя",
        ))
        db.commit()

        products = ProductSyncService(db).extract_unique_products_from_period(
            tenant_id=tenant.id, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)
        )
        assert len(products) == 1
        p = products[0]
        assert p["marketplace_sku"] == "222"      # последняя по sale_dt строка
        assert p["barcode"] == "2222333344440"
        assert p["category"] == "Категория Б"
        assert p["name"] == "Новое имя"


class TestTechnicalRows:

    def test_empty_sku_rows_kept_as_technical_group(self, db, engine, tenant_factory):
        """Хранение/удержание приходят строками БЕЗ артикула. Они не отбрасываются,
        а собираются в техническую группу (sku='', product_name='#-=Technical field=-#')
        — как в задеплоенной матвью. Иначе storage/удержание в аналитике обнуляются."""
        from datetime import date as d
        from app.models.supplier_report import SupplierReport
        from app.models.tax_rate import TaxRate
        from app.services.aggregates_service import (
            recompute_supplier_agg, recompute_product_margins,
        )

        tenant = tenant_factory()
        db.add(TaxRate(tenant_id=tenant.id, tax_rate=0, start_date=d(2000, 1, 1)))
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=8, rrd_id=5001,
            date_from=d(2026, 9, 1), date_to=d(2026, 9, 30), sale_dt=d(2026, 9, 10),
            sku="", doc_type_name="", supplier_oper_name="Хранение",
            bonus_type_name="", quantity=0, storage_fee=1000.50, deduction=0,
            delivery_rub=0, penalty=0, acceptance=0,
        ))
        db.add(SupplierReport(
            tenant_id=tenant.id, realizationreport_id=8, rrd_id=5002,
            date_from=d(2026, 9, 1), date_to=d(2026, 9, 30), sale_dt=d(2026, 9, 12),
            sku="", doc_type_name="", supplier_oper_name="Удержание",
            bonus_type_name="", quantity=0, storage_fee=0, deduction=2500.75,
            delivery_rub=0, penalty=0, acceptance=0,
        ))
        db.commit()

        recompute_supplier_agg(db, tenant.id, months=[d(2026, 9, 1)])
        # строки за разные дни -> две agg-группы (по period_day), обе технические
        tech = db.execute(text(
            "SELECT sku, product_name, sum(storage_fee) AS storage, sum(regular_deduction) AS deduct "
            "FROM supplier_reports_agg WHERE tenant_id = :t "
            "GROUP BY sku, product_name"
        ), {"t": tenant.id}).fetchall()
        assert len(tech) == 1
        assert tech[0].sku == ""
        assert tech[0].product_name == "#-=Technical field=-#"
        assert tech[0].storage == D('1000.50')
        assert tech[0].deduct == D('2500.75')

        # Техническая группа доезжает и до product_margins
        recompute_product_margins(db, tenant.id, months=[d(2026, 9, 1)])
        pm = db.execute(text(
            "SELECT storage_fee, regular_deduction FROM product_margins "
            "WHERE tenant_id = :t AND sku = ''"
        ), {"t": tenant.id}).fetchone()
        assert pm is not None
        assert pm.storage_fee == D('1000.50')
        assert pm.regular_deduction == D('2500.75')


class TestStockUpsertIdempotency:

    def test_stock_upsert_same_key_updates_without_duplicate(self, db, tenant_factory):
        """product_stock_monthly: повторный апсерт того же ключа
        (tenant_id, sku, period_month) обновляет количество, не создавая дублей."""
        from app.services.stock_sync_service import StockSyncService

        tenant = tenant_factory()
        svc = StockSyncService(db)

        svc._upsert_stock(tenant.id, "SKU-STOCK", nm_id="100", period_month=date(2026, 9, 1), quantity=10)
        svc._upsert_stock(tenant.id, "SKU-STOCK", nm_id="100", period_month=date(2026, 9, 1), quantity=25)
        db.commit()

        rows = db.execute(text(
            "SELECT quantity, nm_id FROM product_stock_monthly "
            "WHERE tenant_id = :t AND sku = 'SKU-STOCK'"
        ), {"t": tenant.id}).fetchall()
        assert len(rows) == 1
        assert rows[0].quantity == 25
