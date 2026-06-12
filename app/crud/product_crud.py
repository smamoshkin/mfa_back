from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate
from app.crud.tenant_crud import get_tenant

def get_product(db: Session, product_id: int, tenant_id: int = None):
    """Получить продукт по ID с проверкой tenant"""
    query = db.query(Product).filter(Product.id == product_id)
    if tenant_id is not None:
        query = query.filter(Product.tenant_id == tenant_id)
    return query.first()

def get_products_by_tenant(db: Session, tenant_id: int, skip: int = 0, limit: int = 100):
    return db.query(Product).filter(Product.tenant_id == tenant_id).offset(skip).limit(limit).all()

def get_product_by_sku(db: Session, tenant_id: int, sku: str):
    return db.query(Product).filter(Product.tenant_id == tenant_id, Product.sku == sku).first()

def get_product_by_marketplace_sku(db: Session, tenant_id: int, marketplace_sku: str):
    return db.query(Product).filter(Product.tenant_id == tenant_id, Product.marketplace_sku == marketplace_sku).first()

def create_product(db: Session, product: dict):
    
    # ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ TENANT'А ПЕРВЫМ ДЕЛОМ
    db_tenant = get_tenant(db, tenant_id=product['tenant_id'])
    
    if not db_tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant with id {product['tenant_id']} not found"
        )
    # Проверяем уникальность SKU в рамках tenant
    db_product = get_product_by_sku(db, tenant_id=product['tenant_id'], sku=product['sku'])
    if db_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this SKU already exists for this tenant"
        )
    
    # Проверяем уникальность marketplace_sku в рамках tenant
    db_product = get_product_by_marketplace_sku(db, tenant_id=product['tenant_id'], marketplace_sku=product['marketplace_sku'])
    if db_product:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this marketplace SKU already exists for this tenant"
        )
    
    db_product = Product(**product)
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def update_product(db: Session, product_id: int, product: ProductUpdate):
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        return None
    
    # Если обновляется SKU, проверяем уникальность
    if product.sku and product.sku != db_product.sku:
        existing_product = get_product_by_sku(db, tenant_id=db_product.tenant_id, sku=product.sku)
        if existing_product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product with this SKU already exists for this tenant"
            )
    
    # Если обновляется marketplace_sku, проверяем уникальность
    if product.marketplace_sku and product.marketplace_sku != db_product.marketplace_sku:
        existing_product = get_product_by_marketplace_sku(db, tenant_id=db_product.tenant_id, marketplace_sku=product.marketplace_sku)
        if existing_product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product with this marketplace SKU already exists for this tenant"
            )
    
    update_data = product.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_product, field, value)
    
    db.commit()
    db.refresh(db_product)
    return db_product

def delete_product(db: Session, product_id: int):
    db_product = db.query(Product).filter(Product.id == product_id).first()
    if not db_product:
        return None
    db.delete(db_product)
    db.commit()
    return db_product