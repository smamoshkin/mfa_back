from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal

class SupplierReportBase(BaseModel):
    realizationreport_id: Optional[int] = None
    rrd_id: Optional[int] = None
    date_from: date
    date_to: date
    sale_dt: date
    sku: str
    doc_type_name: str
    supplier_oper_name: str
    quantity: int = 0
    retail_amount: Optional[Decimal] = None
    amount_for_pay: Optional[Decimal] = None
    retail_price: Optional[Decimal] = None
    storage_fee: Optional[Decimal] = None
    bonus_type_name: str
    deduction: Optional[Decimal] = None
    delivery_rub: Optional[Decimal] = None
    penalty: Optional[Decimal] = None
    acceptance: Optional[Decimal] = None
    raw_data: Optional[Dict[str, Any]] = None
    extracted_fields: Optional[Dict[str, Any]] = None

class SupplierReportCreate(SupplierReportBase):
    tenant_id: int

class SupplierReport(SupplierReportBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    tenant_id: int
    created_at: datetime

class ImportResult(BaseModel):
    imported_count: int
    total_received: int
    reports: List[SupplierReport]