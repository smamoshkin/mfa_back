# app/services/analytics_service.py (исправленная версия)
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, List, Any, Optional
import logging
from decimal import Decimal
from app.models.analytics_views import SupplierReportsAggregatedV, ProductMarginsMonthV

logger = logging.getLogger(__name__)

class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db
    
    def get_rentability_report(
        self, 
        tenant_id: int, 
        date_from: date, 
        date_to: date, 
        group_by: str = "month"
    ) -> Dict[str, Any]:
        """
        Полный отчет рентабельности - смешанный подход
        Базовые данные из VIEW + сложная логика в Python
        """
        try:
            # 1. Получаем агрегированные данные из VIEW БД
            base_data = self._get_aggregated_data(tenant_id, date_from, date_to, group_by)
            
            if not base_data:
                return self._get_empty_rent_report(date_from, date_to)
            
            # 2. Агрегируем итоги (простая логика)
            totals = self._calculate_totals(base_data)
            
            # 3. Сложные расчеты рентабельности в Python
            rent_calculations = self._calculate_rentability(totals)
            
            # 4. Детализация по товарам
            product_details = self._get_product_details(base_data)
            
            return {
                "period": {
                    "date_from": date_from.isoformat(),
                    "date_to": date_to.isoformat(),
                    "group_by": group_by
                },
                "totals": totals,
                "rentability": rent_calculations,
                "products": product_details,
                "summary": self._generate_summary(totals, rent_calculations)
            }
            
        except Exception as e:
            logger.error(f"Error generating rentability report: {str(e)}")
            raise
    
    def _get_aggregated_data(
        self, 
        tenant_id: int, 
        date_from: date, 
        date_to: date, 
        group_by: str
    ) -> List[ProductMarginsMonthV]:
        """Получаем данные из VIEW с фильтрацией по периоду"""
        period_column = getattr(ProductMarginsMonthV, f"period_{group_by}")
        
        return self.db.query(ProductMarginsMonthV).filter(
            ProductMarginsMonthV.tenant_id == tenant_id,
            period_column >= date_from,
            period_column <= date_to
        ).all()
    
    def _calculate_totals(self, data: List[ProductMarginsMonthV]) -> Dict[str, Any]:
        """Агрегация итогов из данных VIEW"""
        # 👇 Используем функцию для конвертации Decimal в float
        def _to_float(value):
            if value is None:
                return 0.0
            if isinstance(value, Decimal):
                return float(value)
            return float(value)
        
        return {
            # Основные метрики
            "total_quantity": sum((d.quantity_sold or 0) for d in data),
            "total_revenue": sum(_to_float(d.revenue) for d in data),
            "total_payout": sum(_to_float(d.seller_payout) for d in data),
            "total_margin": sum(_to_float(d.margin) for d in data),
            
            # Расходы
            "total_storage_fee": sum(_to_float(d.storage_fee) for d in data),
            "total_regular_deduction": sum(_to_float(d.regular_deduction) for d in data),
            "total_dzhem_deduction": sum(_to_float(d.dzhem_deduction) for d in data),
            "total_delivery_rub": sum(_to_float(d.delivery_rub) for d in data),
            "total_penalty": sum(_to_float(d.penalty) for d in data),
            "total_acceptance": sum(_to_float(d.acceptance) for d in data),
            "total_return_revenue": sum(_to_float(d.return_revenue) for d in data),
            
            # Дополнительные агрегаты
            "total_tax": sum(_to_float(d.tax) for d in data),
            "total_cost": sum(_to_float(d.total_cost) for d in data),
            "product_count": len(data)
        }
    
    def _calculate_rentability(self, totals: Dict[str, Any]) -> Dict[str, Any]:
        """Сложные расчеты рентабельности (аналог твоего rent report)"""
        # 👇 Убедимся, что все значения float
        total_revenue = float(totals["total_revenue"])
        total_payout = float(totals["total_payout"])
        total_margin = float(totals["total_margin"])
        total_quantity = int(totals["total_quantity"])
        total_regular_deduction = float(totals["total_regular_deduction"])
        total_storage_fee = float(totals["total_storage_fee"])
        total_dzhem_deduction = float(totals["total_dzhem_deduction"])
        
        # Фиксированные расходы (из твоих формул)
        fixed_salary = 60000.0  # ФОТ фиксированный
        
        # Основные расчеты
        margin_minus_expenses = (
            total_margin - 
            total_regular_deduction - 
            total_storage_fee - 
            total_dzhem_deduction
        )
        
        margin_per_unit = (
            margin_minus_expenses / total_quantity 
            if total_quantity > 0 else 0.0
        )
        
        # Процентные показатели
        shop_margin_revenue = (
            total_margin / total_revenue * 100.0 
            if total_revenue > 0 else 0.0
        )
        
        shop_margin_payout = (
            total_margin / total_payout * 100.0 
            if total_payout > 0 else 0.0
        )
        
        drr = (
            total_regular_deduction / total_revenue * 100.0 
            if total_margin > 0 else 0.0
        )
        
        # Расчет премий (твои формулы)
        wb_realized_10p = total_revenue * 0.1
        premium_calculation = total_regular_deduction - wb_realized_10p
        premium_5p = (margin_minus_expenses - premium_calculation) * 0.05
        total_salary = fixed_salary + premium_5p
        margin_10p = margin_minus_expenses * 0.1
        
        # Финальная рентабельность
        margin_after_salary = margin_minus_expenses - margin_10p - total_salary
        profitability = (
            margin_after_salary / total_payout * 100.0 
            if total_payout > 0 else 0.0
        )
        
        return {
            # Основные показатели
            "margin_minus_expenses": float(margin_minus_expenses),
            "margin_per_unit": float(margin_per_unit),
            "shop_margin_revenue": float(shop_margin_revenue),
            "shop_margin_payout": float(shop_margin_payout),
            "drr": float(drr),
            
            # Расчеты зарплат и премий
            "fixed_salary": float(fixed_salary),
            "wb_realized_10p": float(wb_realized_10p),
            "premium_calculation": float(premium_calculation),
            "premium_5p": float(premium_5p),
            "total_salary": float(total_salary),
            "margin_10p": float(margin_10p),
            "margin_after_salary": float(margin_after_salary),
            "profitability": float(profitability),
            
            # Сводка расходов
            "total_advertising": float(total_regular_deduction + totals["total_dzhem_deduction"]),
            "total_logistics": float(totals["total_delivery_rub"] + totals["total_acceptance"])
        }
    
    def _get_product_details(self, data: List[ProductMarginsMonthV]) -> List[Dict[str, Any]]:
        """Детализация по товарам для отчета"""
        def _safe_float(value):
            if value is None:
                return 0.0
            if isinstance(value, Decimal):
                return float(value)
            return float(value)
        
        return [
            {
                "sku": d.sku,
                "product_name": d.product_name,
                "quantity_sold": d.quantity_sold,
                "revenue": _safe_float(d.revenue),
                "margin": _safe_float(d.margin),
                "margin_percent": _safe_float(d.margin_percent_revenue),
                "margin_per_unit": _safe_float(d.margin_per_unit),
                "logistics_per_unit": _safe_float(d.logistics_per_unit)
            }
            for d in data
        ]
    
    def _generate_summary(self, totals: Dict, rentability: Dict) -> Dict[str, Any]:
        """Генерируем текстовую сводку отчета"""
        return {
            "total_revenue": f"₽{totals['total_revenue']:,.2f}",
            "total_margin": f"₽{totals['total_margin']:,.2f}",
            "profitability": f"{rentability['profitability']:.1f}%",
            "margin_per_unit": f"₽{rentability['margin_per_unit']:.2f}",
            "products_count": totals["product_count"]
        }
    
    def _get_empty_rent_report(self, date_from: date, date_to: date) -> Dict[str, Any]:
        """Пустой отчет для случая отсутствия данных"""
        return {
            "period": {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "group_by": "month"
            },
            "totals": {
                "total_quantity": 0,
                "total_revenue": 0.0,
                "total_payout": 0.0,
                "total_margin": 0.0,
                "total_storage_fee": 0.0,
                "total_regular_deduction": 0.0,
                "total_dzhem_deduction": 0.0,
                "total_delivery_rub": 0.0,
                "total_penalty": 0.0,
                "total_acceptance": 0.0,
                "total_return_revenue": 0.0,
                "total_tax": 0.0,
                "total_cost": 0.0,
                "product_count": 0
            },
            "rentability": {
                "margin_minus_expenses": 0.0,
                "margin_per_unit": 0.0,
                "shop_margin_revenue": 0.0,
                "shop_margin_payout": 0.0,
                "drr": 0.0,
                "fixed_salary": 60000.0,
                "wb_realized_10p": 0.0,
                "premium_calculation": 0.0,
                "premium_5p": 0.0,
                "total_salary": 60000.0,
                "margin_10p": 0.0,
                "margin_after_salary": 0.0,
                "profitability": 0.0,
                "total_advertising": 0.0,
                "total_logistics": 0.0
            },
            "products": [],
            "summary": {
                "total_revenue": "₽0",
                "total_margin": "₽0", 
                "profitability": "0%",
                "margin_per_unit": "₽0",
                "products_count": 0
            }
        }