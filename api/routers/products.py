from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from decimal import Decimal

from api.database import get_db
from api.models import Product


router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    top_features: Optional[List[str]] = None
    category: Optional[str] = None
    is_live: bool = False
    is_sellable: bool = False
    selling_price: Optional[Decimal] = None
    original_price: Optional[Decimal] = None
    discount_percentage: Optional[Decimal] = None
    retailers: Optional[List[Any]] = None


class ProductUpdate(ProductCreate):
    pass


class ProductOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    top_features: Optional[List[str]]
    category: Optional[str]
    is_live: bool
    is_sellable: bool
    selling_price: Optional[Decimal]
    original_price: Optional[Decimal]
    discount_percentage: Optional[Decimal]
    retailers: Optional[List[Any]]

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/products", response_model=List[ProductOut])
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
