# app/services/product_sync_service.py
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Any, Optional
import logging
from datetime import date, datetime
from app.models.product import Product
from app.models.product_stock import ProductStockMonthly
from app.crud.product_crud import create_product, get_product_by_sku, update_product
from app.schemas.product import ProductCreate, ProductUpdate
from app.services.wb_api_client import WBAPIClient

logger = logging.getLogger(__name__)

# Пауза между последовательными запросами фото к WB Content API:
# за один синк может создаться много новых товаров, а подряд идущие вызовы
# без задержки легко ловят 429 (см. WBAPIClient.get_product_data_by_sku)
PHOTO_FETCH_DELAY_SECONDS = 1

class ProductSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.wb_client = WBAPIClient()
    
    def extract_unique_products_from_period(self, tenant_id: int, date_from: date, date_to: date) -> List[Dict[str, Any]]:
        """Извлекаем уникальные продукты из отчетов за период (последняя версия по SKU)"""
        
        logger.info(f"🔍 Извлекаем уникальные продукты для tenant_id={tenant_id} за период {date_from} - {date_to}")
        
        query = text("""
            SELECT tenant_id, sku, marketplace_sku, barcode, category, name
            FROM (
                SELECT 
                    row_number() over (partition by (s.sku) order by s.sale_dt desc) as rn,
                    s.tenant_id,
                    s.sku,
                    s.raw_data ->> 'nmId' as marketplace_sku,
                    s.raw_data ->> 'sku' as barcode,
                    s.raw_data ->> 'subjectName' as category,
                    s.raw_data ->> 'title' as name
                FROM public.supplier_reports s
                WHERE 1=1
                    AND s.date_from >= :date_from
                    AND s.date_to <= :date_to
                    AND s.tenant_id = :tenant_id
                    AND s.sku != '0'
                    AND s.sku IS NOT NULL
                    AND s.sku != ''
            ) x
            WHERE rn = 1
        """)
        
        result = self.db.execute(query, {
            'date_from': date_from,
            'date_to': date_to, 
            'tenant_id': tenant_id
        }).fetchall()
        
        unique_products = []
        for row in result:
            product_data = {
                'tenant_id': row[0],
                'sku': row[1],
                'marketplace_sku': row[2] or row[1],  # Если marketplace_sku нет, используем sku
                'barcode': row[3],
                'category': row[4],
                'name': row[5]
            }
            unique_products.append(product_data)

        logger.info(f"📊 Найдено {len(unique_products)} уникальных продуктов")
        return unique_products
    
    async def fetch_product_photo(self, api_key: str, sku: str) -> Optional[str]:
        """
        Запрашивает карточку товара в WB Content API по артикулу продавца (sku)
        и возвращает ссылку на фото (square) первого найденного изображения.

        Если у товара нет фото или карточка не найдена — возвращает None,
        это нормальная ситуация, а не ошибка.
        """
        try:
            cards = await self.wb_client.get_product_data_by_sku(
                api_key=api_key, sku=sku, limit=1, with_photo=1
            )
        except Exception as e:
            logger.warning(f"⚠️ Не удалось получить фото для {sku} из WB API: {str(e)}")
            return None

        if not cards:
            return None

        photos = cards[0].get('photos') or []
        if not photos:
            return None

        return photos[0].get('square') or None

    def _consolidate_marketplace_sku_duplicate(self, tenant_id: int, new_product: Product) -> Dict[str, int]:
        """
        Консолидация дублей по marketplace_sku при синке из WB-отчётов.

        Свежие данные из WB считаются актуальными: если у созданного товара
        оказался тот же marketplace_sku, что и у существующих товаров тенанта,
        существующие деактивируются, а их остатки за текущий и будущие месяцы
        удаляются (история за прошлые месяцы сохраняется — она не искажает
        аналитику закрытых периодов).

        Переносить остатки новому товару вручную не нужно: шаг синка остатков
        (StockSyncService) идёт сразу после синка товаров и запишет новому
        (активному) товару полный остаток WB-карточки по nmId.

        Внимание: эта логика — только для пути синка. Ручное создание товара
        с фронта с тем же marketplace_sku НЕ деактивирует существующие
        (там показывается предупреждение, оба остаются активными).
        """
        duplicates = self.db.query(Product).filter(
            Product.tenant_id == tenant_id,
            Product.marketplace_sku == new_product.marketplace_sku,
            Product.id != new_product.id,
        ).all()

        if not duplicates:
            return {'deactivated': 0, 'stock_rows_deleted': 0}

        current_month_start = date.today().replace(day=1)
        duplicate_skus = [d.sku for d in duplicates]

        # Деактивируем только активных, но хвосты остатков чистим у всех
        # (могли остаться с прошлых синков до появления этой логики)
        deactivated = 0
        for dup in duplicates:
            if dup.is_active:
                dup.is_active = False
                dup.updated_at = datetime.utcnow()
                deactivated += 1

        stock_rows_deleted = self.db.query(ProductStockMonthly).filter(
            ProductStockMonthly.tenant_id == tenant_id,
            ProductStockMonthly.sku.in_(duplicate_skus),
            ProductStockMonthly.period_month >= current_month_start,
        ).delete(synchronize_session=False)

        self.db.commit()

        logger.info(
            f"🔁 Консолидация дублей marketplace_sku={new_product.marketplace_sku} "
            f"(tenant_id={tenant_id}): деактивировано {deactivated} из {len(duplicates)} "
            f"[{', '.join(duplicate_skus)}], удалено строк остатков с {current_month_start}: "
            f"{stock_rows_deleted}. Остаток новому товару {new_product.sku} запишет синк остатков."
        )
        return {'deactivated': deactivated, 'stock_rows_deleted': stock_rows_deleted}

    async def sync_products_from_period(self, tenant_id: int, date_from: date, date_to: date, api_key: Optional[str] = None) -> Dict[str, int]:
        """Синхронизируем продукты из отчетов за период"""

        unique_products = self.extract_unique_products_from_period(tenant_id, date_from, date_to)

        created_count = 0
        skipped_count = 0

        for product_data in unique_products:
            try:
                sku = product_data['sku']

                # Проверяем, существует ли уже продукт
                existing_product = get_product_by_sku(self.db, tenant_id, sku)

                if not existing_product:
                    logger.info(f"Продукт {sku} не существует. Попробуем создать.")
                    # Создаем новый продукт с базовыми данными
                    product_create = ProductCreate(
                        sku=sku,
                        marketplace_sku=product_data['marketplace_sku'],
                        name=product_data['name'],
                        category=product_data['category'] or "",
                        barcode=product_data['barcode'] or "",
                        is_active=True
                    )
                    logger.info(f"Для {sku} создали объект, пытаюсь вставить.")
                    product_dict = product_create.model_dump()
                    product_dict['tenant_id'] = tenant_id
                    new_product = create_product(self.db, product_dict)
                    created_count += 1
                    logger.debug(f"✅ Создан продукт: {sku}")

                    # Если у нового товара тот же marketplace_sku, что и у существующих —
                    # деактивируем старые дубли и чистим их остатки текущего месяца+
                    # (новому товару остатки запишет последующий шаг синка остатков)
                    self._consolidate_marketplace_sku_duplicate(tenant_id, new_product)

                    # Фото подтягиваем только для нового товара — если у существующего
                    # его нет, это не повод дёргать WB API при каждой синхронизации.
                    if api_key:
                        # Пауза между фото-запросами: за один синк новых товаров
                        # может быть много, подряд идущие вызовы Content API
                        # без задержки легко ловят 429
                        await asyncio.sleep(PHOTO_FETCH_DELAY_SECONDS)
                        photo_url = await self.fetch_product_photo(api_key, sku)
                        if photo_url:
                            update_product(self.db, new_product.id, ProductUpdate(foto=photo_url))
                            logger.debug(f"🖼️ Сохранено фото для продукта: {sku}")
                        else:
                            logger.debug(f"ℹ️ Фото для продукта {sku} не найдено в WB API")
                else:
                    skipped_count += 1
                    logger.debug(f"⏭️ Пропущен существующий продукт: {sku}")

            except Exception as e:
                logger.error(f"❌ Ошибка при синхронизации продукта {product_data.get('sku')}: {str(e)}")
                continue

        logger.info(f"🎯 Синхронизация завершена: создано {created_count}, пропущено {skipped_count}")

        return {
            'created': created_count,
            'skipped': skipped_count,
            'total_processed': len(unique_products)
        }
    
    def enrich_products_from_marketplace_api(self, tenant_id: int, api_key: str, skus: List[str]) -> Dict[str, int]:
        """
        Обогащаем данные продуктов из API маркетплейса
        TODO: Реализовать вызов реального API
        """
        
        logger.info(f"🔄 Обогащаем данные для {len(skus)} продуктов из API маркетплейса")
        
        updated_count = 0
        failed_count = 0
        
        for sku in skus:
            try:
                # Получаем продукт из БД
                product = get_product_by_sku(self.db, tenant_id, sku)
                if not product:
                    logger.warning(f"⚠️ Продукт {sku} не найден в БД")
                    continue
                
                # TODO: Реализовать вызов API маркетплейса
                # Пример структуры вызова:
                api_data = self.wb_client.get_product_data_by_sku(api_key=api_key, sku=sku)
                # api_data = self._mock_marketplace_api_call(sku, product.marketplace_sku)
                
                if api_data:
                    product_info = {
                        'name': api_data.get('title', ''),
                        'description': api_data.get('description', '')
                    }

                    # Извлекаем фото (первое изображение из массива photos)
                    photos = api_data.get('photos', [])
                    if photos and len(photos) > 0:
                        first_photo = photos[0]
                        # Используем square изображение как основное фото
                        product_info['foto'] = first_photo.get('square', '')
                    # Обновляем продукт данными из API
                    update_data = ProductUpdate(**product_info)
                    
                    updated_product = update_product(self.db, product.id, update_data)
                    if updated_product:
                        updated_count += 1
                        logger.debug(f"✅ Обновлен продукт из API: {sku}")
                    else:
                        failed_count += 1
                else:
                    failed_count += 1
                    logger.warning(f"⚠️ Нет данных из API для продукта: {sku}")
                    
            except Exception as e:
                logger.error(f"❌ Ошибка при обогащении продукта {sku}: {str(e)}")
                failed_count += 1
                continue
        
        logger.info(f"🎯 Обогащение завершено: обновлено {updated_count}, ошибок {failed_count}")
        
        return {
            'updated': updated_count,
            'failed': failed_count,
            'total_processed': len(skus)
        }
    
    async def sync_and_enrich_products(self, tenant_id: int, date_from: date, date_to: date) -> Dict[str, Any]:
        """
        Полная синхронизация: извлечение продуктов + обогащение из API
        """

        logger.info(f"🚀 Запускаем полную синхронизацию продуктов для tenant_id={tenant_id}")

        # Шаг 1: Синхронизируем продукты из отчетов
        sync_stats = await self.sync_products_from_period(tenant_id, date_from, date_to)
        
        # Шаг 2: Получаем список SKU для обогащения
        unique_products = self.extract_unique_products_from_period(tenant_id, date_from, date_to)
        skus_to_enrich = [product['sku'] for product in unique_products]
        
        # Шаг 3: Обогащаем данные из API
        enrich_stats = self.enrich_products_from_marketplace_api(tenant_id, skus_to_enrich)
        
        result = {
            'sync': sync_stats,
            'enrich': enrich_stats,
            'success': True
        }
        
        logger.info(f"🎯 Полная синхронизация завершена: {result}")
        return result
    
    async def batch_sync_products(self, tenant_id: int, periods: List[Dict[str, date]]) -> Dict[str, int]:
        """Пакетная синхронизация за несколько периодов"""

        total_stats = {'created': 0, 'skipped': 0, 'total_processed': 0}

        for period in periods:
            date_from = period['date_from']
            date_to = period['date_to']

            logger.info(f"🔄 Синхронизация продуктов за период {date_from} - {date_to}")

            stats = await self.sync_products_from_period(tenant_id, date_from, date_to)
            
            for key in total_stats:
                total_stats[key] += stats[key]
        
        logger.info(f"🎯 Пакетная синхронизация завершена: {total_stats}")
        return total_stats