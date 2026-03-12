import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from api.database import get_db
from api.models import Product
from api.services.scraper import scrape_product

router = APIRouter()


async def _run_product(product: Product) -> dict:
    """Scrape a single product and return the result dict."""
    return await scrape_product(product)


@router.post("/sync/run/{product_id}")
async def sync_single(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    result = await _run_product(product)
    return result


@router.post("/sync/run")
async def sync_all(db: Session = Depends(get_db)):
    products = db.query(Product).all()
    if not products:
        return []

    BATCH_SIZE = 3
    all_results = []

    for i in range(0, len(products), BATCH_SIZE):
        batch = products[i: i + BATCH_SIZE]
        # Within each batch, all products run in parallel
        batch_results = await asyncio.gather(*[_run_product(p) for p in batch])
        all_results.extend(batch_results)

    return all_results
