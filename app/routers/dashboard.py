# routes/dashboard.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_, or_
from datetime import datetime, timedelta, date
from typing import List, Optional
from decimal import Decimal
from app.routers.auth import get_current_tenant
from app.database.database import get_db
from ..models import Tenant, Product, SupplierReport, ProductCost
from ..schemas.dashboard import (
    DashboardResponse,
    DashboardMetrics,
    SalesData,
    TopProduct,
    ActivityItem,
    SyncRequest,
    SyncResponse
)
from ..models.analytics_views import (
    SupplierReportsAggregatedV, 
    ProductMarginsMonthV
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def calculate_period_dates(period: str) -> tuple:
    """Вычисляет даты начала и конца периода"""
    today = datetime.now().date()
    
    if period == '7days':
        start_date = today - timedelta(days=7)
    elif period == '30days':
        start_date = today - timedelta(days=30)
    elif period == '90days':
        start_date = today - timedelta(days=90)
    else:
        start_date = today - timedelta(days=30)  # по умолчанию
    
    return start_date, today


@router.get("", response_model=DashboardResponse)
async def get_dashboard_data(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получение полных данных дашборда"""
    try:
        # Получаем все данные параллельно
        metrics = get_metrics(current_tenant.id, db)
        sales_chart = get_sales_chart_data_internal(current_tenant.id, '30days', db)
        top_products = get_top_products_internal(current_tenant.id, 5, db)
        recent_activity = get_recent_activity_internal(current_tenant.id, db)
        
        # Получаем последнюю синхронизацию
        last_sync = db.query(SupplierReport.created_at)\
            .filter(SupplierReport.tenant_id == current_tenant.id)\
            .order_by(SupplierReport.created_at.desc())\
            .first()
        
        return DashboardResponse(
            metrics=metrics,
            salesChart=sales_chart,
            topProducts=top_products,
            recentActivity=recent_activity,
            lastSync=last_sync[0].isoformat() if last_sync else datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка получения данных: {str(e)}")


@router.get("/metrics", response_model=DashboardMetrics)
async def get_metrics_endpoint(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получение основных метрик"""
    return get_metrics(current_tenant.id, db)


def get_metrics(tenant_id: int, db: Session) -> DashboardMetrics:
    """Внутренняя функция для расчета метрик"""
    # Текущий месяц
    today = datetime.now().date()
    first_day_of_month = date(today.year, today.month, 1)
    
    # Предыдущий месяц
    if today.month == 1:
        prev_month = date(today.year - 1, 12, 1)
    else:
        prev_month = date(today.year, today.month - 1, 1)
    
    # Продажи за текущий месяц
    current_month_sales = db.query(func.sum(SupplierReport.quantity))\
        .filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.sale_dt >= first_day_of_month,
            SupplierReport.sale_dt <= today,
            SupplierReport.supplier_oper_name.ilike('%Продажа%')
        )\
        .scalar() or 0
    
    # Продажи за предыдущий месяц
    prev_month_sales = db.query(func.sum(SupplierReport.quantity))\
        .filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.sale_dt >= prev_month,
            SupplierReport.sale_dt < first_day_of_month,
            SupplierReport.supplier_oper_name.ilike('%Продажа%')
        )\
        .scalar() or 0
    
    # Выручка за текущий месяц
    current_month_revenue = db.query(func.sum(SupplierReport.retail_amount))\
        .filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.sale_dt >= first_day_of_month,
            SupplierReport.sale_dt <= today,
            SupplierReport.supplier_oper_name.ilike('%Продажа%')
        )\
        .scalar() or Decimal('0')
    
    # Выручка за предыдущий месяц
    prev_month_revenue = db.query(func.sum(SupplierReport.retail_amount))\
        .filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.sale_dt >= prev_month,
            SupplierReport.sale_dt < first_day_of_month,
            SupplierReport.supplier_oper_name.ilike('%Продажа%')
        )\
        .scalar() or Decimal('0')
    
    # Количество товаров
    products_count = db.query(func.count(Product.id))\
        .filter(
            Product.tenant_id == tenant_id,
            Product.is_active == True
        )\
        .scalar() or 0
    
    # Количество товаров неделю назад (для расчета изменений)
    week_ago_products = db.query(func.count(Product.id))\
        .filter(
            Product.tenant_id == tenant_id,
            Product.is_active == True,
            Product.created_at <= datetime.now() - timedelta(days=7)
        )\
        .scalar() or 0
    
    # Рентабельность (средняя по товарам из ProductMarginsMonthV)
    avg_margin = db.query(func.avg(ProductMarginsMonthV.margin_percent_revenue))\
        .filter(
            ProductMarginsMonthV.tenant_id == tenant_id,
            ProductMarginsMonthV.period_month >= first_day_of_month
        )\
        .scalar() or Decimal('0')
    
    # Рентабельность за предыдущий месяц
    prev_avg_margin = db.query(func.avg(ProductMarginsMonthV.margin_percent_revenue))\
        .filter(
            ProductMarginsMonthV.tenant_id == tenant_id,
            ProductMarginsMonthV.period_month >= prev_month,
            ProductMarginsMonthV.period_month < first_day_of_month
        )\
        .scalar() or Decimal('0')
    
    # Расчет изменений в процентах
    sales_change = calculate_percentage_change(current_month_sales, prev_month_sales)
    revenue_change = calculate_percentage_change(float(current_month_revenue), float(prev_month_revenue))
    products_change = products_count - week_ago_products
    profitability_change = calculate_percentage_change(float(avg_margin), float(prev_avg_margin))
    
    return DashboardMetrics(
        sales=current_month_sales,
        revenue=float(current_month_revenue),
        products=products_count,
        profitability=float(avg_margin),
        sales_change=sales_change,
        revenue_change=revenue_change,
        products_change=products_change,
        profitability_change=profitability_change
    )


@router.get("/sales-chart", response_model=List[SalesData])
async def get_sales_chart_data(
    period: str = Query('30days', description="Период: 7days, 30days, 90days"),
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получение данных для графика продаж"""
    return get_sales_chart_data_internal(current_tenant.id, period, db)


def get_sales_chart_data_internal(tenant_id: int, period: str, db: Session) -> List[SalesData]:
    """Внутренняя функция для получения данных графика"""
    start_date, end_date = calculate_period_dates(period)
    
    # Группируем продажи по дням
    daily_sales = db.query(
        func.date(SupplierReport.sale_dt).label('date'),
        func.sum(SupplierReport.quantity).label('sales'),
        func.sum(SupplierReport.retail_amount).label('revenue')
    )\
    .filter(
        SupplierReport.tenant_id == tenant_id,
        SupplierReport.sale_dt >= start_date,
        SupplierReport.sale_dt <= end_date,
        SupplierReport.supplier_oper_name.ilike('%Продажа%')
    )\
    .group_by(func.date(SupplierReport.sale_dt))\
    .order_by(func.date(SupplierReport.sale_dt))\
    .all()
    
    # Если нет данных, возвращаем пустой массив или заглушку
    if not daily_sales:
        return []
    
    # Форматируем результат
    result = []
    for day in daily_sales:
        result.append(SalesData(
            date=day.date.isoformat(),
            sales=day.sales or 0,
            revenue=float(day.revenue or 0)
        ))
    
    return result


@router.get("/top-products", response_model=List[TopProduct])
async def get_top_products(
    limit: int = Query(5, ge=1, le=20, description="Количество товаров"),
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получение топ товаров по продажам"""
    return get_top_products_internal(current_tenant.id, limit, db)


def get_top_products_internal(tenant_id: int, limit: int, db: Session) -> List[TopProduct]:
    """Внутренняя функция для получения топ товаров"""
    
    # Используем представление ProductMarginsMonthV для более точных данных
    top_products_query = db.query(
        ProductMarginsMonthV.sku,
        ProductMarginsMonthV.product_name,
        ProductMarginsMonthV.quantity_sold,
        ProductMarginsMonthV.revenue,
        ProductMarginsMonthV.margin_percent_revenue,
        Product.foto
    )\
    .join(Product, and_(
        Product.tenant_id == tenant_id,
        Product.sku == ProductMarginsMonthV.sku
    ))\
    .filter(
        ProductMarginsMonthV.tenant_id == tenant_id,
        ProductMarginsMonthV.period_month >= datetime.now().date().replace(day=1)
    )\
    .order_by(ProductMarginsMonthV.quantity_sold.desc())\
    .limit(limit)\
    .all()
    
    if not top_products_query:
        # Альтернативный запрос если представление пустое
        top_products_query = db.query(
            SupplierReport.sku,
            func.sum(SupplierReport.quantity).label('quantity_sold'),
            func.sum(SupplierReport.retail_amount).label('revenue'),
            Product.name,
            Product.foto
        )\
        .join(Product, and_(
            Product.tenant_id == tenant_id,
            Product.sku == SupplierReport.sku
        ))\
        .filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.supplier_oper_name.ilike('%Продажа%'),
            SupplierReport.sale_dt >= datetime.now().date() - timedelta(days=30)
        )\
        .group_by(SupplierReport.sku, Product.name, Product.foto)\
        .order_by(func.sum(SupplierReport.quantity).desc())\
        .limit(limit)\
        .all()
        
        result = []
        for idx, product in enumerate(top_products_query):
            # Оценочная рентабельность
            estimated_profitability = 20.0 - (idx * 3)  # Просто для примера
            result.append(TopProduct(
                id=idx + 1,
                name=product.name or f"Товар {product.sku}",
                sku=product.sku,
                sales=product.quantity_sold or 0,
                revenue=float(product.revenue or 0),
                profitability=estimated_profitability,
                image_url=product.foto
            ))
        return result
    
    # Используем данные из представления
    result = []
    for idx, product in enumerate(top_products_query):
        result.append(TopProduct(
            id=idx + 1,
            name=product.product_name or f"Товар {product.sku}",
            sku=product.sku,
            sales=product.quantity_sold or 0,
            revenue=float(product.revenue or 0),
            profitability=float(product.margin_percent_revenue or 0),
            image_url=product.foto
        ))
    
    return result


@router.get("/recent-activity", response_model=List[ActivityItem])
async def get_recent_activity(
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Получение последней активности"""
    return get_recent_activity_internal(current_tenant.id, db)


def get_recent_activity_internal(tenant_id: int, db: Session) -> List[ActivityItem]:
    """Внутренняя функция для получения активности"""
    activities = []
    
    # 1. Последние продажи
    recent_sales = db.query(SupplierReport)\
        .filter(
            SupplierReport.tenant_id == tenant_id,
            SupplierReport.supplier_oper_name.ilike('%Продажа%')
        )\
        .order_by(SupplierReport.created_at.desc())\
        .limit(3)\
        .all()
    
    for sale in recent_sales:
        activities.append(ActivityItem(
            time=sale.created_at.isoformat(),
            action=f"Продажа товара {sale.sku}",
            status="success",
            details=f"Количество: {sale.quantity}"
        ))
    
    # 2. Последние добавленные товары
    recent_products = db.query(Product)\
        .filter(Product.tenant_id == tenant_id)\
        .order_by(Product.created_at.desc())\
        .limit(2)\
        .all()
    
    for product in recent_products:
        activities.append(ActivityItem(
            time=product.created_at.isoformat(),
            action=f"Добавлен товар {product.sku}",
            status="info",
            details=product.name
        ))
    
    # 3. Последние обновления себестоимости
    recent_costs = db.query(ProductCost)\
        .join(Product, Product.id == ProductCost.product_id)\
        .filter(Product.tenant_id == tenant_id)\
        .order_by(ProductCost.created_at.desc())\
        .limit(2)\
        .all()
    
    for cost in recent_costs:
        activities.append(ActivityItem(
            time=cost.created_at.isoformat(),
            action="Обновлена себестоимость",
            status="info",
            details=f"Товар ID: {cost.product_id}"
        ))
    
    # Сортируем по времени и берем последние 5
    activities.sort(key=lambda x: x.time, reverse=True)
    return activities[:5]


@router.post("/sync", response_model=SyncResponse)
async def start_sync(
    sync_request: SyncRequest,
    current_tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db)
):
    """Запуск синхронизации с Wildberries"""
    # Здесь будет логика синхронизации с WB API
    # Пока что имитация
    
    # Записываем факт начала синхронизации
    sync_time = datetime.now()
    
    # В реальности здесь будет вызов WB API
    await simulate_wb_sync(current_tenant, db)
    
    return SyncResponse(
        success=True,
        message="Синхронизация успешно завершена",
        lastSync=sync_time.isoformat(),
        syncedItems=42  # Примерное количество
    )


async def simulate_wb_sync(tenant: Tenant, db: Session):
    """Имитация синхронизации с WB"""
    # В реальности здесь будет:
    # 1. Запрос к WB API
    # 2. Парсинг отчетов
    # 3. Сохранение в базу
    # 4. Обновление агрегированных данных
    
    # Пока просто ждем 1 секунду для имитации
    import asyncio
    await asyncio.sleep(1)
    
    # Можно добавить запись в лог синхронизации
    return True


def calculate_percentage_change(current: float, previous: float) -> float:
    """Расчет процентного изменения"""
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 1)