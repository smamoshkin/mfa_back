from datetime import datetime
from typing import List, Dict, Any
from app.schemas.supplier_report import SupplierReportCreate

class ReportMapperService:
    """Сервис для преобразования сырых данных API в наши модели"""
    
    def map_wb_report_to_model(self, raw_data: Dict[str, Any], tenant_id: int) -> SupplierReportCreate:
        """
        Преобразует данные из WB API в нашу модель SupplierReportCreate
        Берет только нужные поля, остальное уходит в raw_data
        """
        
        # Извлекаем только нужные нам поля
        mapped_data = {
            'tenant_id': tenant_id,
            'realizationreport_id': raw_data.get('reportId'),
            'rrd_id': raw_data.get('rrdId'),
            'date_from': self._parse_date(raw_data.get('dateFrom')),
            'date_to': self._parse_date(raw_data.get('dateTo')),
            'sale_dt': self._parse_date(raw_data.get('saleDt') or raw_data.get('rrDate')),
            'sku': raw_data.get('vendorCode'),  
            'doc_type_name': raw_data.get('docTypeName', ''),
            'supplier_oper_name': raw_data.get('sellerOperName', ''),
            'quantity': raw_data.get('quantity', 0),
            'retail_amount': raw_data.get('retailAmount'),
            'amount_for_pay': raw_data.get('forPay'),  
            'retail_price': raw_data.get('retailPrice'),
            'storage_fee': raw_data.get('paidStorage'),
            'bonus_type_name': raw_data.get('bonusTypeName', ''),
            'deduction': raw_data.get('deduction'),
            'delivery_rub': raw_data.get('deliveryService'),
            'penalty': raw_data.get('penalty'),
            'acceptance': raw_data.get('paidAcceptance'),
            'raw_data': raw_data  # 👈 ВСЕ оригинальные данные сохраняем здесь
        }
        
        # Очищаем None значения для обязательных полей
        if not mapped_data['sku']:
            mapped_data['sku'] = str(raw_data.get('nm_id', ''))  # Используем nm_id если нет sa_name
        
        return SupplierReportCreate(**mapped_data)
    
    def _parse_date(self, date_str: Any) -> datetime.date:
        """Парсит дату из строки"""
        if not date_str:
            return None
        try:
            if isinstance(date_str, str):
                # Пробуем разные форматы дат
                for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S'):
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except ValueError:
                        continue
            elif isinstance(date_str, datetime):
                return date_str.date()
        except (ValueError, TypeError):
            return None
        return None
    
    def bulk_map_wb_reports(self, raw_reports: List[Dict[str, Any]], tenant_id: int) -> List[SupplierReportCreate]:
        """Массовое преобразование отчетов WB"""
        mapped_reports = []
        
        for raw_report in raw_reports:
            try:
                mapped_report = self.map_wb_report_to_model(raw_report, tenant_id)
                mapped_reports.append(mapped_report)
            except Exception as e:
                # Логируем ошибки маппинга, но продолжаем обработку
                print(f"Error mapping report: {e}")
                continue
        
        return mapped_reports