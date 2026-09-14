# tests/conftest.py
"""
Фикстуры тестов рекламного модуля.

Тестам нужен настоящий PostgreSQL (материализованные view, JSONB,
advisory locks) — SQLite не подходит.

Схема разворачивается так:
  1) create_all() для ВСЕХ таблиц, КРОМЕ двух новых рекламных (их создаёт
     наш DDL-скрипт — он и проверяется);
  2) DDL-скрипты db/tables/wb_ad_*.sql и db/materialized_views/*.sql
     в порядке нумерации (01 → 03 → 04 → 05).

DSN берётся из TEST_DATABASE_URL (по умолчанию — локальный throwaway-контейнер
faapp-test-pg на 127.0.0.1:5433, см. README тестов).
"""
import os
import pathlib

# ⚠️ ДО любого импорта app.*: направляем ДВИЖОК ПРИЛОЖЕНИЯ на тестовую БД.
# app.database.database читает DATABASE_URL при первом импорте; без этого
# сервисный REFRESH (refresh_advertising_materialized_views) ходил бы в БД
# из .env разработчика. load_dotenv() существующие переменные не переопределяет.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://marketfinance_user:marketfinance_dev@127.0.0.1:5433/marketfinance_db",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Таблицы, которые НЕ создаёт create_all(): рекламные факт-таблицы (их создаёт
# DDL-скрипт — он и проверяется тестами) и все мат.view (create_all по ORM-моделям
# view создал бы ОБЫЧНЫЕ ТАБЛИЦЫ с теми же именами — DROP MATERIALIZED VIEW
# в DDL тогда падает с WrongObjectType).
EXCLUDE_FROM_CREATE_ALL = (
    "wb_ad_expense_operations",
    "wb_ad_product_daily_stats",
    "supplier_reports_agg",
    "product_margins",
    "supplier_reports_agg_mv",
    "product_margins_mv",
    "mv_wb_ad_actual_expense_by_nm_day",
    "mv_wb_ad_actual_expense_by_nm_month",
    # обычные view тоже применяются вручную
    "supplier_reports_aggregated_v",
    "product_margins_month_v",
)

DDL_ORDER = [
    ROOT / "db" / "tables" / "wb_ad_expense_operations.sql",
    ROOT / "db" / "tables" / "wb_ad_product_daily_stats.sql",
    ROOT / "db" / "tables" / "supplier_reports_agg.sql",
    ROOT / "db" / "tables" / "product_margins.sql",
    ROOT / "db" / "scripts" / "03_supplier_reports_extract_fields.sql",  # колонки supplier_reports
    ROOT / "db" / "materialized_views" / "03_create_mv_wb_ad_actual_expense_by_nm_day.sql",
    ROOT / "db" / "materialized_views" / "04_create_mv_wb_ad_actual_expense_by_nm_month.sql",
]


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    # 1) базовые таблицы (tenants, products, ...), но НЕ рекламные — их создаст DDL
    non_ad_tables = [t for name, t in Base.metadata.tables.items()
                     if name not in EXCLUDE_FROM_CREATE_ALL]
    Base.metadata.create_all(engine, tables=non_ad_tables)
    # 2) DDL рекламных таблиц и всех мат.view — в порядке зависимостей
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for ddl_file in DDL_ORDER:
            conn.execute(text(ddl_file.read_text(encoding="utf-8")))
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    """Сессия с очисткой рекламных данных между тестами."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        # FK CASCADE от tenants, но чистим точечно, чтобы не пересоздавать схему
        conn.execute(text("TRUNCATE wb_ad_expense_operations, wb_ad_product_daily_stats"))
    refresh_views(engine)


@pytest.fixture
def tenant_factory(db):
    """Фабрика тенантов с уникальными email (изоляция тестов по tenant_id)."""
    from app.models.tenant import Tenant

    def _make_tenant():
        import uuid
        tenant = Tenant(
            name=f"Ad Test Tenant {uuid.uuid4().hex[:8]}",
            login_email=f"ad-test-{uuid.uuid4().hex[:12]}@test.local",
            hashed_password="x",
        )
        db.add(tenant)
        db.flush()
        return tenant

    return _make_tenant


def refresh_views(engine):
    """Пересчёт таблиц агрегатов для всех тенантов + REFRESH рекламных MV.

    Порядок (важен): agg (сырьё, там себестоимость/налог) → рекламные MV →
    product_margins (читает agg и рекламную месячную MV).
    """
    from app.services.aggregates_service import recompute_supplier_agg, recompute_product_margins

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("REFRESH MATERIALIZED VIEW mv_wb_ad_actual_expense_by_nm_day"))
        conn.execute(text("REFRESH MATERIALIZED VIEW mv_wb_ad_actual_expense_by_nm_month"))

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        tenant_ids = [r[0] for r in db.execute(text("SELECT DISTINCT tenant_id FROM supplier_reports"))]
        for tid in tenant_ids:
            recompute_supplier_agg(db, tid)
            recompute_product_margins(db, tid)
    finally:
        db.close()
