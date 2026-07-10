# app/services/sync_service.py (обновленная версия)
import time
import asyncio
from datetime import date
from typing import Dict
from sqlalchemy.orm import Session
from app.services.wb_api_client import WBAPIClient
from app.services.report_mapper import ReportMapperService
from app.services.product_sync_service import ProductSyncService  # 👈 Добавляем
from app.crud.supplier_report_crud import bulk_create_reports_DEBUG
from app.models.tenant import Tenant
import logging

logger = logging.getLogger(__name__)

class SyncService:
    def __init__(self):
        self.wb_client = WBAPIClient()
        self.mapper = ReportMapperService()
    
    async def sync_wb_data_for_period(
        self,
        db: Session,
        tenant: Tenant,
        date_from: date,
        date_to: date,
        sync_products: bool = True  # 👈 Новый параметр
    ) -> Dict:
        """
        Синхронизация с пагинацией и пакетной вставкой
        Вставляет данные батчами по 100k
        """
        metrics = {
            'total_time': 0,
            'total_records': 0,
            'api_calls': 0,
            'batches_processed': 0,
            'last_rrdid': 0,
            'products_synced': 0  # 👈 Добавляем метрику для продуктов
        }
        
        start_time = time.time()
        rrdid = 0
        page = 1
        
        try:
            logger.info(f"🔄 Starting paginated sync for tenant {tenant.id} from {date_from} to {date_to}")
            
            while True:
                batch_metrics = await self._process_single_batch(
                    db=db,
                    tenant=tenant,
                    date_from=date_from,
                    date_to=date_to,
                    rrdid=rrdid,
                    page=page
                )
                
                metrics['total_records'] += batch_metrics['records_imported']
                metrics['api_calls'] += 1
                metrics['batches_processed'] += 1
                metrics['last_rrdid'] = batch_metrics['last_rrdid']
                
                # Если получили пустой массив - вероятно, данные кончились
                if batch_metrics['batch_size'] == 0:
                    logger.info("✅ Received empty array from API - sync completed!")
                    break
                
                # Подготавливаем следующий запрос
                rrdid = batch_metrics['last_rrdid']
                page += 1
                
                # Ждем 65 секунд перед следующим запросом
                logger.info("⏳ Waiting 65 seconds before next batch...")
                await asyncio.sleep(65)
            
            # ШАГ СИНХРОНИЗАЦИИ ПРОДУКТОВ
            if sync_products and metrics['total_records'] > 0:
                products_metrics = await self._sync_products_from_reports(
                    db=db,
                    tenant=tenant,
                    date_from=date_from,
                    date_to=date_to
                )
                metrics['products_synced'] = products_metrics['created']
            else:
                logger.info("⏭️ Product sync skipped")
            
            metrics['total_time'] = time.time() - start_time
            
            logger.info(f"""
🎯 PAGINATED SYNC COMPLETE:
├── Total time: {metrics['total_time']:.2f}s
├── Total records: {metrics['total_records']}
├── API calls: {metrics['api_calls']}
├── Batches processed: {metrics['batches_processed']}
├── Products synced: {metrics['products_synced']}
└── Last rrdid: {metrics['last_rrdid']}
""")
            
            return metrics
            
        except Exception as e:
            metrics['total_time'] = time.time() - start_time
            logger.error(f"❌ Paginated sync failed after {metrics['total_time']:.2f}s: {str(e)}")
            raise
    
    async def _sync_products_from_reports(
        self,
        db: Session,
        tenant: Tenant,
        date_from: date,
        date_to: date
    ) -> Dict[str, int]:
        """Синхронизация продуктов из загруженных отчетов"""
        
        logger.info(f"🔄 Starting product sync from reports for tenant {tenant.id}")
        
        try:
            product_sync_service = ProductSyncService(db)
            
            # Синхронизируем продукты из отчетов за период
            products_stats = product_sync_service.sync_products_from_period(
                tenant_id=tenant.id,
                date_from=date_from,
                date_to=date_to
            )
            
            logger.info(f"✅ Product sync completed: {products_stats}")
            return products_stats
            
        except Exception as e:
            logger.error(f"❌ Product sync failed: {str(e)}")
            return {'created': 0, 'skipped': 0, 'total_processed': 0}
    
    async def _process_single_batch(
        self,
        db: Session,
        tenant: Tenant,
        date_from: date,
        date_to: date,
        rrdid: int,
        page: int
    ) -> Dict:
        """Обработка одного батча данных"""
        batch_metrics = {
            'batch_size': 0,
            'records_imported': 0,
            'last_rrdid': rrdid
        }
        
        logger.info(f"📦 Processing batch {page} (rrdid: {rrdid})")
        
        try:
            # 1. Запрос к API
            api_start = time.time()
            wb_data = await self.wb_client.get_report_detail_by_period(
                api_key=tenant.wb_api_key,
                date_from=date_from,
                date_to=date_to,
                rrdid=rrdid
            )
            api_time = time.time() - api_start

        except Exception as e:
            # 🔥 ОБРАБОТКА ИСКЛЮЧЕНИЙ ОТ API
            error_msg = str(e)
            
            # Если это код 204 (нет данных) - это нормальное завершение
            if "204" in error_msg:
                logger.info(f"ℹ️ Batch {page}: No more data (HTTP 204) - sync completed")
                batch_metrics['batch_size'] = 0
                return batch_metrics
            else:
                # Другие ошибки - прокидываем выше
                logger.error(f"❌ Batch {page}: API request failed: {error_msg}")
                raise
        
        if not wb_data:
            logger.info(f"ℹ️ Batch {page}: no data received")
            return batch_metrics
        
        batch_metrics['batch_size'] = len(wb_data)
        logger.info(f"✅ Batch {page}: received {len(wb_data)} records in {api_time:.2f}s")
        
        # 2. Маппинг
        mapping_start = time.time()
        reports_to_create = self.mapper.bulk_map_wb_reports(wb_data, tenant.id)
        mapping_time = time.time() - mapping_start
        
        if not reports_to_create:
            logger.warning(f"⚠️ Batch {page}: no valid reports after mapping")
            return batch_metrics
        
        logger.info(f"🔄 Batch {page}: mapped {len(reports_to_create)} records in {mapping_time:.2f}s")
        
        # 3. Вставка в БД
        db_start = time.time()
        records_imported = bulk_create_reports_DEBUG(db, reports_to_create, tenant.id)
        
        db_time = time.time() - db_start
        
        batch_metrics['records_imported'] = records_imported
        
        # 4. Получаем last_rrdid для следующего запроса
        if wb_data:
            last_rrdid = wb_data[-1].get('rrdId')
            if last_rrdid:
                batch_metrics['last_rrdid'] = last_rrdid
        
        logger.info(f"💾 Batch {page}: inserted {records_imported} records in {db_time:.2f}s")
        
        return batch_metrics
    
    async def sync_with_products_enrichment(
        self,
        db: Session,
        tenant: Tenant,
        date_from: date,
        date_to: date
    ) -> Dict:
        """
        Полная синхронизация с обогащением данных продуктов из API
        """
        metrics = {
            'total_time': 0,
            'total_records': 0,
            'products_synced': 0,
            'products_enriched': 0
        }
        
        start_time = time.time()
        
        try:
            # Шаг 1: Синхронизация отчетов и базовых продуктов
            sync_metrics = await self.sync_wb_data_for_period(
                db=db,
                tenant=tenant,
                date_from=date_from,
                date_to=date_to,
                sync_products=True
            )
            
            metrics['total_records'] = sync_metrics['total_records']
            metrics['products_synced'] = sync_metrics['products_synced']
            
            # Шаг 2: Обогащение данных продуктов из API маркетплейса
            if metrics['products_synced'] > 0:
                enrichment_metrics = await self._enrich_products_from_api(
                    db=db,
                    tenant=tenant,
                    date_from=date_from,
                    date_to=date_to
                )
                metrics['products_enriched'] = enrichment_metrics['updated']
            
            metrics['total_time'] = time.time() - start_time
            
            logger.info(f"""
🎯 FULL SYNC WITH ENRICHMENT COMPLETE:
├── Total time: {metrics['total_time']:.2f}s
├── Reports synced: {metrics['total_records']}
├── Products created: {metrics['products_synced']}
└── Products enriched: {metrics['products_enriched']}
""")
            
            return metrics
            
        except Exception as e:
            metrics['total_time'] = time.time() - start_time
            logger.error(f"❌ Full sync with enrichment failed: {str(e)}")
            raise
    
    async def _enrich_products_from_api(
        self,
        db: Session,
        tenant: Tenant,
        date_from: date,
        date_to: date
    ) -> Dict[str, int]:
        """Обогащение данных продуктов из API маркетплейса"""
        
        logger.info(f"🔄 Starting product enrichment from API for tenant {tenant.id}")
        
        try:
            product_sync_service = ProductSyncService(db)
            
            # Получаем список SKU для обогащения
            unique_products = product_sync_service.extract_unique_products_from_period(
                tenant_id=tenant.id,
                date_from=date_from,
                date_to=date_to
            )
            
            skus_to_enrich = [product['sku'] for product in unique_products]
            
            if not skus_to_enrich:
                logger.info("ℹ️ No products to enrich")
                return {'updated': 0, 'failed': 0, 'total_processed': 0}
            
            # Обогащаем данные из API
            enrichment_stats = product_sync_service.enrich_products_from_marketplace_api(
                tenant_id=tenant.id,
                api_key=tenant.wb_api_key,
                skus=skus_to_enrich
            )
            
            logger.info(f"✅ Product enrichment completed: {enrichment_stats}")
            return enrichment_stats
            
        except Exception as e:
            logger.error(f"❌ Product enrichment failed: {str(e)}")
            return {'updated': 0, 'failed': 0, 'total_processed': 0}