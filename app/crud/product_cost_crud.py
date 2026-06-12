from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from fastapi import HTTPException, status
from app.models.product_cost import ProductCost
from app.models.product import Product
from app.schemas.product_cost import ProductCostCreate, ProductCostUpdate

# def get_product_cost(db: Session, cost_id: int, tenant_id: int = None):
#     """Получить запись о себестоимости по ID"""
#     db.query(ProductCost).filter(ProductCost.id == cost_id).first()
#     if tenant_id is not None:
#         query = query.join(Product).filter(Product.tenant_id == tenant_id)
#     return query.first()

def get_product_cost(db: Session, cost_id: int, tenant_id: int):
    """Получить запись о себестоимости по ID"""
    # Сначала находим себестоимость с проверкой принадлежности товара tenant'у
    cost = db.query(ProductCost).join(
        Product, ProductCost.product_id == Product.id
    ).filter(
        ProductCost.id == cost_id,
        Product.tenant_id == tenant_id
    ).first()
    
    return cost

def get_costs_by_product(db: Session, product_id: int, tenant_id: int, skip: int = 0, limit: int = 100):
    """Получить все себестоимости для продукта"""
    # Сначала проверяем, что продукт принадлежит tenant
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == tenant_id).first()
    if not product:
        return []  # Возвращаем пустой массив вместо исключения
    
    return db.query(ProductCost).filter(
        ProductCost.product_id == product_id
    ).order_by(
        ProductCost.start_date.desc()
    ).offset(skip).limit(limit).all()

def get_current_cost(db: Session, product_id: int, tenant_id: int):
    """Получить текущую актуальную себестоимость продукта"""
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == tenant_id).first()
    if not product:
        return None  # Возвращаем None вместо исключения
    
    return db.query(ProductCost).filter(
        ProductCost.product_id == product_id,
        ProductCost.end_date.is_(None)
    ).order_by(
        ProductCost.start_date.desc()
    ).first()

def get_cost_by_date(db: Session, product_id: int, target_date: date, tenant_id: int):
    """Получить себестоимость на конкретную дату"""
    product = db.query(Product).filter(Product.id == product_id, Product.tenant_id == tenant_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or access denied"
        )
    
    return db.query(ProductCost).filter(
        ProductCost.product_id == product_id,
        ProductCost.start_date <= target_date,
        or_(
            ProductCost.end_date.is_(None),
            ProductCost.end_date >= target_date
        )
    ).order_by(
        ProductCost.start_date.desc()
    ).first()

def create_product_cost(db: Session, cost: ProductCostCreate, tenant_id: int):
    """Создать новую запись о себестоимости"""
    
    # Проверяем существование продукта и права доступа
    db_product = db.query(Product).filter(Product.id == cost.product_id, Product.tenant_id == tenant_id).first()
    if not db_product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found or access denied"
        )
    
    # 👇 ИСПРАВЛЕННАЯ ПРОВЕРКА ПЕРЕСЕЧЕНИЯ ДАТ
    # Проверяем пересечение интервалов для этого продукта
    # Новый интервал: [cost.start_date, cost.end_date или None]
    # Существующий интервал: [existing.start_date, existing.end_date или None]
    
    existing_cost_query = db.query(ProductCost).filter(
        ProductCost.product_id == cost.product_id
    )
    
    if cost.end_date:
        # Новый интервал имеет end_date
        # Пересечение происходит если:
        # 1. Новый интервал начинается внутри существующего
        # 2. Новый интервал заканчивается внутри существующего  
        # 3. Новый интервал полностью содержит существующий
        # 4. Существующий интервал полностью содержит новый
        
        existing_cost = existing_cost_query.filter(
            or_(
                # Случай 1: Новый start_date внутри существующего интервала
                and_(
                    ProductCost.start_date <= cost.start_date,
                    or_(
                        ProductCost.end_date.is_(None),
                        ProductCost.end_date >= cost.start_date
                    )
                ),
                # Случай 2: Новый end_date внутри существующего интервала
                and_(
                    ProductCost.start_date <= cost.end_date,
                    or_(
                        ProductCost.end_date.is_(None),
                        ProductCost.end_date >= cost.end_date
                    )
                ),
                # Случай 3: Новый интервал полностью содержит существующий
                and_(
                    cost.start_date <= ProductCost.start_date,
                    cost.end_date >= ProductCost.end_date
                ),
                # Случай 4: Существующий интервал полностью содержит новый
                and_(
                    ProductCost.start_date <= cost.start_date,
                    or_(
                        ProductCost.end_date.is_(None),
                        and_(
                            ProductCost.end_date >= cost.end_date
                        )
                    )
                )
            )
        ).first()
    else:
        # Новый интервал бесконечный (нет end_date)
        # Пересечение происходит если существующий интервал:
        # 1. Начинается после нового start_date ИЛИ
        # 2. Бесконечный (тоже нет end_date) ИЛИ  
        # 3. Заканчивается после нового start_date
        
        existing_cost = existing_cost_query.filter(
            or_(
                # Существующий начинается после нового start_date
                ProductCost.start_date >= cost.start_date,
                # Существующий тоже бесконечный
                ProductCost.end_date.is_(None),
                # Существующий заканчивается после нового start_date
                and_(
                    ProductCost.end_date.isnot(None),
                    ProductCost.end_date >= cost.start_date
                )
            )
        ).first()
    
    if existing_cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cost record overlaps with existing period: {existing_cost.start_date} to {existing_cost.end_date or 'present'}"
        )
    
    # Создаем новую запись
    db_cost = ProductCost(**cost.model_dump())
    db.add(db_cost)
    db.commit()
    db.refresh(db_cost)
    
    # Обновляем текущую себестоимость в продукте (опционально)
    if not cost.end_date:  # Если это текущая цена
        db_product.current_cost = cost.cost
        db.commit()
        db.refresh(db_product)
    
    return db_cost

def update_product_cost(db: Session, cost_id: int, cost: ProductCostUpdate, tenant_id: int):
    """Обновить запись о себестоимости"""
    db_cost = get_product_cost(db, cost_id=cost_id, tenant_id=tenant_id)
    if not db_cost:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product cost not found or access denied"
        )
    
    # Проверяем пересечение дат (если обновляется start_date)
    if cost.start_date and cost.start_date != db_cost.start_date:
        existing_cost = db.query(ProductCost).filter(
            ProductCost.product_id == db_cost.product_id,
            ProductCost.id != cost_id,  # Исключаем текущую запись
            and_(
                ProductCost.start_date <= cost.start_date,
                or_(
                    ProductCost.end_date.is_(None),
                    ProductCost.end_date >= cost.start_date
                )
            )
        ).first()
        
        if existing_cost:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cost record already exists for this date range"
            )
    
    update_data = cost.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_cost, field, value)
    
    db.commit()
    db.refresh(db_cost)
    
    # Обновляем текущую себестоимость в продукте если нужно
    if not db_cost.end_date:  # Если это текущая цена
        db_product = db.query(Product).filter(Product.id == db_cost.product_id).first()
        if db_product:
            db_product.current_cost = db_cost.cost
            db.commit()
    
    return db_cost

def delete_product_cost(db: Session, cost_id: int, tenant_id: int):
    """Удалить запись о себестоимости"""
    db_cost = get_product_cost(db, cost_id=cost_id, tenant_id=tenant_id)
    if not db_cost:
        return None  # Возвращаем None вместо исключения
        # raise HTTPException(
        #     status_code=status.HTTP_404_NOT_FOUND,
        #     detail="Product cost not found or access denied"
        # )
    
    db.delete(db_cost)
    db.commit()
    return db_cost

def close_cost_period(db: Session, cost_id: int, end_date: date, tenant_id: int):
    """Закрыть период действия себестоимости"""
    db_cost = get_product_cost(db, cost_id=cost_id, tenant_id=tenant_id)
    if not db_cost:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product cost not found or access denied"
        )
    
    db_cost.end_date = end_date
    db.commit()
    db.refresh(db_cost)
    return db_cost