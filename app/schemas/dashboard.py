# schemas/dashboard.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import List, Optional
from decimal import Decimal


class DashboardMetrics(BaseModel):
    """Метрики дашборда"""
    sales: int
    revenue: float
    products: int
    profitability: float  # Средняя рентабельность в процентах
    
    # Изменения (опционально)
    sales_change: Optional[float] = None
    revenue_change: Optional[float] = None
    products_change: Optional[int] = None
    profitability_change: Optional[float] = None


class SalesData(BaseModel):
    """Данные для графика продаж"""
    date: str  # ISO формат даты
    sales: int
    revenue: float


class TopProduct(BaseModel):
    """Топ товар"""
    id: int
    name: str
    sku: Optional[str] = None
    sales: int
    revenue: float
    profitability: float
    image_url: Optional[str] = None
    category: Optional[str] = None


class ActivityItem(BaseModel):
    """Элемент активности"""
    time: str  # ISO формат времени
    action: str
    status: str  # success, info, warning, error
    details: Optional[str] = None


class DashboardResponse(BaseModel):
    """Полный ответ дашборда"""
    metrics: DashboardMetrics
    salesChart: List[SalesData]
    topProducts: List[TopProduct]
    recentActivity: List[ActivityItem]
    lastSync: str  # ISO формат времени последней синхронизации


class SyncRequest(BaseModel):
    """Запрос на синхронизацию"""
    force: bool = False


class SyncResponse(BaseModel):
    """Ответ на синхронизацию"""
    success: bool
    message: str
    lastSync: str
    syncedItems: int