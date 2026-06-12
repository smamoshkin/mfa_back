# app/services/product_sync_service.py
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Any, Optional
import logging
from datetime import date, datetime
from app.models.product import Product
from app.crud.product_crud import create_product, get_product_by_sku, update_product
from app.schemas.product import ProductCreate, ProductUpdate
from app.services.wb_api_client import WBAPIClient

logger = logging.getLogger(__name__)

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
    
    def sync_products_from_period(self, tenant_id: int, date_from: date, date_to: date) -> Dict[str, int]:
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
                        tenant_id=tenant_id,
                        sku=sku,
                        marketplace_sku=product_data['marketplace_sku'],
                        name=product_data['name'],  
                        category=product_data['category'] or "",
                        barcode=product_data['barcode'] or "",
                        is_active=True
                    )
                    logger.info(f"Для {sku} создали объект, пытаюсь вставить.")
                    create_product(self.db, product_create.model_dump())
                    created_count += 1
                    logger.debug(f"✅ Создан продукт: {sku}")
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
    
    def sync_and_enrich_products(self, tenant_id: int, date_from: date, date_to: date) -> Dict[str, Any]:
        """
        Полная синхронизация: извлечение продуктов + обогащение из API
        """
        
        logger.info(f"🚀 Запускаем полную синхронизацию продуктов для tenant_id={tenant_id}")
        
        # Шаг 1: Синхронизируем продукты из отчетов
        sync_stats = self.sync_products_from_period(tenant_id, date_from, date_to)
        
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
    
    def batch_sync_products(self, tenant_id: int, periods: List[Dict[str, date]]) -> Dict[str, int]:
        """Пакетная синхронизация за несколько периодов"""
        
        total_stats = {'created': 0, 'skipped': 0, 'total_processed': 0}
        
        for period in periods:
            date_from = period['date_from']
            date_to = period['date_to']
            
            logger.info(f"🔄 Синхронизация продуктов за период {date_from} - {date_to}")
            
            stats = self.sync_products_from_period(tenant_id, date_from, date_to)
            
            for key in total_stats:
                total_stats[key] += stats[key]
        
        logger.info(f"🎯 Пакетная синхронизация завершена: {total_stats}")
        return total_stats