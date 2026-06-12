from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List
from app.database.database import get_db
from app.schemas.product import Product, ProductCreate, ProductUpdate
from app.crud import product_crud
from app.routers.auth import get_current_tenant  # 👈 ДОБАВЛЯЕМ

router = APIRouter(
    prefix="/products",
    tags=["products"]
)

@router.post("/", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(
    product: ProductCreate,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    try:
        # Создаем словарь с данными продукта и добавляем tenant_id
        product_data = product.model_dump()
        product_data["tenant_id"] = current_tenant.id  # ← добавляем здесь
        print("'I'm here. Tenant_id = ", product_data['tenant_id'])
        return product_crud.create_product(db=db, product=product_data)
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this SKU or marketplace SKU already exists"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@router.get("/", response_model=List[Product])
def read_products_by_tenant(
    skip: int = 0, 
    limit: int = 100,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    # Автоматически фильтруем по текущему tenant
    return product_crud.get_products_by_tenant(
        db, tenant_id=current_tenant.id, skip=skip, limit=limit
    )

@router.get("/{product_id}", response_model=Product)
def read_product(
    product_id: int,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    db_product = product_crud.get_product(db, product_id=product_id)
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Проверяем, что продукт принадлежит текущему tenant
    if db_product.tenant_id != current_tenant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    return db_product

@router.put("/{product_id}", response_model=Product)
def update_product(
    product_id: int, 
    product: ProductUpdate,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    # Сначала проверяем существование и права
    db_product = product_crud.get_product(db, product_id=product_id)
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if db_product.tenant_id != current_tenant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    try:
        return product_crud.update_product(db, product_id=product_id, product=product)
    except HTTPException:
        raise
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this SKU or marketplace SKU already exists"
        )

@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    db_product = product_crud.get_product(db, product_id=product_id)
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if db_product.tenant_id != current_tenant.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    result = product_crud.delete_product(db, product_id=product_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}

# Дополнительные эндпоинты для поиска - тоже защищаем
@router.get("/sku/{sku}", response_model=Product)
def get_product_by_sku(
    sku: str,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    db_product = product_crud.get_product_by_sku(db, tenant_id=current_tenant.id, sku=sku)
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product

@router.get("/marketplace-sku/{marketplace_sku}", response_model=Product)
def get_product_by_marketplace_sku(
    marketplace_sku: str,
    current_tenant = Depends(get_current_tenant),  # 👈 ЗАЩИТА
    db: Session = Depends(get_db)
):
    db_product = product_crud.get_product_by_marketplace_sku(db, tenant_id=current_tenant.id, marketplace_sku=marketplace_sku)
    if db_product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return db_product