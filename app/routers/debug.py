# app/routers/debug.py
from fastapi import APIRouter, Depends, HTTPException, status
from app.models.tenant import Tenant  # 👈 ДОБАВЬ ЭТОТ ИМПОРТ
from app.models.product import Product
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException
from app.database.database import get_db

router = APIRouter(
    prefix="/debug",
    tags=["debug"]
)

@router.get("/debug/tenant-products/{tenant_id}")
def debug_tenant_products(tenant_id: int, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)  # 👈 Теперь Tenant будет определен
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    
    return {
        "tenant": tenant.name,
        "products_count": len(tenant.products),
        "products": [
            {"id": p.id, "name": p.name, "sku": p.sku} 
            for p in tenant.products
        ]
    }