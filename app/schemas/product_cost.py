from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from typing import List, Optional
from decimal import Decimal

class ProductCostBase(BaseModel):
    cost: Decimal
    start_date: date
    end_date: Optional[date] = None
    created_by: Optional[str] = None

class ProductCostCreate(ProductCostBase):
    product_id: int

class ProductCostUpdate(BaseModel):
    cost: Optional[Decimal] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_by: Optional[str] = None

class ProductCost(ProductCostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Импорт себестоимостей из файла (xlsx/csv)
# ---------------------------------------------------------------------------

class CostImportRowReport(BaseModel):
    """Отчёт по одной строке файла импорта."""
    row_num: int                      # номер строки в файле (1-based, включая шапку)
    sku: Optional[str] = None
    product_name: Optional[str] = None
    cost: Optional[Decimal] = None
    start_date: Optional[date] = None
    # create — новая запись; update — обновит существующую запись с той же датой;
    # error — строка не будет обработана (причина в message)
    action: str
    message: Optional[str] = None

class CostImportSummary(BaseModel):
    created: int = 0
    updated: int = 0
    closed_periods: int = 0          # сколько открытых периодов будет/было закрыто
    errors: int = 0
    total_rows: int = 0

class CostImportReport(BaseModel):
    dry_run: bool
    rows: List[CostImportRowReport]
    summary: CostImportSummary
    mv_refresh_ms: Optional[int] = None  # только для dry_run=False