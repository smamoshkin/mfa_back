# app/services/stock_sync_service.py
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func
from typing import Dict, List
from datetime import date
import logging

from app.models.product import Product
from app.models.product_stock import ProductStockMonthly
from app.services.wb_api_client import WBAPIClient

logger = logging.getLogger(__name__)

# Сколько дней с начала недели считается "недавним" переходом через границу
# месяца. Отсекает initial/manual синки с далёким date_from (там дублировать
# снапшот в старый месяц было бы некорректно — стока за полгода назад это не
# отражает).
RECENT_WEEK_BOUNDARY_DAYS = 10


class StockSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.wb_client = WBAPIClient()

    def _target_periods(self, week_start: date, today: date) -> List[date]:
        """
        Определяет, в какие period_month нужно записать снапшот остатков.

        Обычно — только текущий месяц (today). Но если синхронизируемая неделя
        началась в другом месяце, чем today, и это произошло недавно (реальный
        недельный синк, а не historical backfill) — дублируем снапшот и в
        закрывающийся месяц: там он станет самым свежим известным значением
        для уже завершившегося месяца.
        """
        periods = {today.replace(day=1)}

        same_month = (week_start.year, week_start.month) == (today.year, today.month)
        recently_started = (today - week_start).days <= RECENT_WEEK_BOUNDARY_DAYS

        if not same_month and recently_started:
            periods.add(week_start.replace(day=1))

        return sorted(periods)

    async def sync_tenant_stocks(
        self,
        tenant_id: int,
        api_key: str,
        week_start: date,
        today: date = None,
    ) -> Dict[str, int]:
        """
        Синхронизирует остатки на складах WB для всех товаров тенанта и
        сохраняет их в product_stock_monthly за нужный(е) месяц(ы).
        """
        today = today or date.today()

        products = self.db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.marketplace_sku.isnot(None),
            Product.marketplace_sku != "",
        ).all()

        if not products:
            logger.info(f"ℹ️ Нет товаров для синхронизации остатков (tenant_id={tenant_id})")
            return {"products_processed": 0, "products_updated": 0}

        nm_id_to_sku: Dict[str, str] = {}
        nm_ids: List[int] = []
        for product in products:
            try:
                nm_id = int(product.marketplace_sku)
            except (TypeError, ValueError):
                logger.warning(
                    f"⚠️ Некорректный marketplace_sku у продукта {product.sku}: {product.marketplace_sku}"
                )
                continue
            nm_ids.append(nm_id)
            nm_id_to_sku[str(nm_id)] = product.sku

        if not nm_ids:
            return {"products_processed": 0, "products_updated": 0}

        try:
            items = await self.wb_client.get_stocks_report(api_key=api_key, nm_ids=nm_ids)
        except Exception as e:
            logger.error(f"❌ Не удалось получить остатки из WB API для tenant_id={tenant_id}: {str(e)}")
            return {"products_processed": len(nm_ids), "products_updated": 0}

        # Суммируем quantity по всем складам для каждого nmId
        quantity_by_nm_id: Dict[str, int] = {}
        for item in items:
            nm_id = str(item.get("nmId"))
            quantity_by_nm_id[nm_id] = quantity_by_nm_id.get(nm_id, 0) + (item.get("quantity") or 0)

        periods = self._target_periods(week_start, today)

        updated_count = 0
        for nm_id, sku in nm_id_to_sku.items():
            quantity = quantity_by_nm_id.get(nm_id, 0)
            for period_month in periods:
                self._upsert_stock(tenant_id, sku, nm_id, period_month, quantity)
            updated_count += 1

        self.db.commit()

        logger.info(
            f"🎯 Остатки синхронизированы: tenant_id={tenant_id}, "
            f"товаров={updated_count}, периоды={periods}"
        )

        return {"products_processed": len(nm_ids), "products_updated": updated_count}

    def _upsert_stock(self, tenant_id: int, sku: str, nm_id: str, period_month: date, quantity: int):
        stmt = pg_insert(ProductStockMonthly).values(
            tenant_id=tenant_id,
            sku=sku,
            nm_id=nm_id,
            period_month=period_month,
            quantity=quantity,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "sku", "period_month"],
            set_={
                "quantity": stmt.excluded.quantity,
                "nm_id": stmt.excluded.nm_id,
                "updated_at": func.now(),
            },
        )
        self.db.execute(stmt)
