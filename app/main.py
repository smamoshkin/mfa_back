from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.database import get_db, engine
from app.models import Base
from app.models import tenant, product, product_cost, supplier_report  # импорт моделей для создания таблиц
from app.routers import products, debug, product_costs, supplier_reports, sync, celery_tasks, auth, analytics, periodic_sync, dashboard, tax_rates, tenants  # импортируем роутеры
import logging
import os
from fastapi.middleware.cors import CORSMiddleware


logging.basicConfig(level=logging.INFO)

root_path = os.getenv("ROOT_PATH", "")

# Создаем таблицы (временно, потом заменим на Alembic)
tenant.Base.metadata.create_all(bind=engine)
product.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Marketplace Finance API",
    description="API для автоматизации финансовой отчетности",
    version="0.1.0",
    root_path=root_path,
    docs_url="/docs",
    openapi_url="/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173",
                   "http://localhost:5174",
                   "http://188.127.240.202",
    		   "http://188.127.240.202:8080"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(tenants.router)
app.include_router(products.router)
# app.include_router(debug.router)
app.include_router(product_costs.router)
app.include_router(supplier_reports.router)
app.include_router(sync.router) 
app.include_router(celery_tasks.router)
app.include_router(periodic_sync.router)
app.include_router(dashboard.router)
app.include_router(tax_rates.router)

# # Создаем таблицы в БД
# Base.metadata.create_all(bind=engine)

# app = FastAPI(title="Marketplace Finance API")

@app.get("/")
def read_root():
    return {"message": "Marketplace Finance API is running!"}

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    # Простая проверка, что БД доступна
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
    
