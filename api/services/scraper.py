"""
Playwright-based async scraper for product data integrity checking.

For each retailer attached to a product, this module:
  1. Opens the retailer URL
  2. Uses the CSS locators defined in the retailer's `locators` dict to find each element
  3. Extracts the text / existence of the element
  4. Takes a screenshot of each located element (encoded as base64)
  5. Compares the found value against the expected value stored in the DB product

Special handling:
  - top_features: ordered list comparison
  - add_to_cart / is_sellable: check element existence → compare to product.is_sellable
  - locator_not_found: returned when no element matches
"""

import asyncio
import base64
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from playwright.async_api import async_playwright, Locator, Page


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_text(raw: str) -> str:
    """Strip extra whitespace from extracted text."""
    return re.sub(r"\s+", " ", raw).strip()


def _parse_decimal(text: str) -> Optional[float]:
    """Try to parse a price / percentage string as float."""
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


async def _screenshot_b64(locator: Locator) -> Optional[str]:
    """Return a base64-encoded PNG screenshot of the first element matched by locator."""
    try:
        screenshot_bytes = await locator.first.screenshot(type="png")
        return base64.b64encode(screenshot_bytes).decode("utf-8")
    except Exception:
        return None


async def _extract_field(page: Page, css: str, field_name: str) -> tuple[Any, Optional[str]]:
    """
    Locate element by CSS selector, return (value, screenshot_b64).
    Returns ("locator_not_found", None) when element is absent.
    """
    try:
        loc = page.locator(css)
        count = await loc.count()
        if count == 0:
            return "locator_not_found", None

        screenshot = await _screenshot_b64(loc)

        if field_name == "top_features":
            # Collect all <li> text nodes under the locator
            items_loc = loc.first.locator("li")
            items_count = await items_loc.count()
            if items_count > 0:
                texts = []
                for i in range(items_count):
                    t = await items_loc.nth(i).inner_text()
                    cleaned = _clean_text(t)
                    if cleaned:
                        texts.append(cleaned)
                return texts, screenshot
            else:
                # Fall back to inner_text of the container
                raw = await loc.first.inner_text()
                lines = [_clean_text(line) for line in raw.splitlines() if _clean_text(line)]
                return lines, screenshot

        elif field_name == "add_to_cart":
            # Return True if the button is visible
            visible = await loc.first.is_visible()
            return visible, screenshot

        elif field_name in ("selling_price", "original_price", "discount_percentage"):
            raw = await loc.first.inner_text()
            return _parse_decimal(_clean_text(raw)), screenshot

        else:
            raw = await loc.first.inner_text()
            return _clean_text(raw), screenshot

    except Exception:
        return "locator_not_found", None


def _compare(field_name: str, expected: Any, found: Any) -> bool:
    """Return True if expected and found values are considered matching."""
    if found == "locator_not_found":
        return False

    if field_name == "top_features":
        # Ordered list comparison
        return expected == found

    if field_name in ("selling_price", "original_price", "discount_percentage"):
        try:
            return abs(float(expected) - float(found)) < 0.01
        except (TypeError, ValueError):
            return False

    if field_name == "is_sellable":
        # found is a bool (cart button existence)
        return bool(expected) == bool(found)

    # String comparison (case-insensitive, whitespace-normalised)
    return str(expected).strip().lower() == str(found).strip().lower()


# ── Core scraping for one retailer ───────────────────────────────────────────

FIELD_MAP = {
    "name": "name",
    "description": "description",
    "top_features": "top_features",
    "category": "category",
    "add_to_cart": "is_sellable",   # maps add_to_cart locator → is_sellable field
    "selling_price": "selling_price",
    "original_price": "original_price",
    "discount_percentage": "discount_percentage",
}


async def _scrape_retailer(page: Page, retailer: dict, product: Any) -> dict:
    """
    Scrape a single retailer page.
    Returns the retailer result dict as per the spec response shape.
    """
    url = retailer.get("url", "")
    platform = retailer.get("platform", "")
    locators: dict = retailer.get("locators", {})

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        return {
            "platform": platform,
            "url": url,
            "error": f"Failed to load page: {e}",
            "fields": {},
        }

    fields_result = {}

    for locator_key, css in locators.items():
        product_field = FIELD_MAP.get(locator_key, locator_key)

        # Determine expected value
        if locator_key == "add_to_cart":
            expected = getattr(product, "is_sellable", None)
        else:
            raw_expected = getattr(product, product_field, None)
            # Convert Decimal to float for JSON serialisation
            if isinstance(raw_expected, Decimal):
                expected = float(raw_expected)
            else:
                expected = raw_expected

        found, screenshot = await _extract_field(page, css, locator_key)

        # For is_sellable the expected is bool, found is bool (from add_to_cart)
        if locator_key == "add_to_cart":
            match = _compare("is_sellable", expected, found)
            fields_result["is_sellable"] = {
                "expected": expected,
                "found": found,
                "match": match,
                "screenshot": screenshot,
            }
        else:
            # For top_features expected might come as list
            if isinstance(expected, Decimal):
                expected = float(expected)

            match = _compare(product_field, expected, found)
            fields_result[product_field] = {
                "expected": expected,
                "found": found,
                "match": match,
                "screenshot": screenshot,
            }

    return {
        "platform": platform,
        "url": url,
        "fields": fields_result,
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_product(product: Any) -> dict:
    """
    Scrape all retailers for a single product, in parallel.
    Returns the full result dict per the spec response shape.
    """
    retailers = product.retailers or []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            async def scrape_one(retailer: dict) -> dict:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                page = await context.new_page()
                try:
                    result = await _scrape_retailer(page, retailer, product)
                finally:
                    await context.close()
                return result

            retailer_results = await asyncio.gather(*[scrape_one(r) for r in retailers])
        finally:
            await browser.close()

    return {
        "product_id": product.id,
        "product_name": product.name,
        "retailers": list(retailer_results),
    }
