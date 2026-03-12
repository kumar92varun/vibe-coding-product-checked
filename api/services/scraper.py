"""
Playwright-based async scraper for product data integrity checking.

For each retailer attached to a product, this module:
  1. Opens the retailer URL with full JS rendering (waits for networkidle)
  2. Applies stealth settings to reduce bot-detection blockage
  3. Uses the CSS locators defined in the retailer's `locators` dict
  4. Waits up to ELEMENT_TIMEOUT ms for each element to appear in the DOM
  5. Takes a screenshot of each located element (base64-encoded PNG)
  6. Compares found values against expected values from the DB product

Special handling:
  - top_features:          ordered list comparison
  - add_to_cart/is_sellable: check element visibility → compare to product.is_sellable
  - locator_not_found:     returned when element is absent after the wait
"""

import asyncio
import base64
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from playwright.async_api import async_playwright, Locator, Page


# ── Config ────────────────────────────────────────────────────────────────────

# How long (ms) to wait for each element to appear in the DOM
ELEMENT_TIMEOUT = 15000

# How long (ms) to wait for the page to reach networkidle
PAGE_TIMEOUT = 60000

# Extra settle time (ms) after networkidle — gives JS frameworks time to finish rendering
SETTLE_MS = 2000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_text(raw: str) -> str:
    """Strip extra whitespace from extracted text."""
    return re.sub(r"\s+", " ", raw).strip()


def _parse_decimal(text: str) -> Optional[float]:
    """Try to parse a price / percentage string as float (e.g. '₹1,299' → 1299.0)."""
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None


async def _screenshot_b64(locator: Locator) -> Optional[str]:
    """Return a base64-encoded PNG screenshot of the first matched element."""
    try:
        screenshot_bytes = await locator.first.screenshot(type="png")
        return base64.b64encode(screenshot_bytes).decode("utf-8")
    except Exception:
        return None


async def _extract_field(page: Page, css: str, field_name: str) -> tuple[Any, Optional[str]]:
    """
    Wait for a CSS selector to appear, then extract its value.
    Returns ("locator_not_found", None) if the element never appears.
    """
    try:
        loc = page.locator(css)

        # Wait for the element to be present in the DOM
        await loc.first.wait_for(state="attached", timeout=ELEMENT_TIMEOUT)

        # Confirm at least one element matched
        count = await loc.count()
        if count == 0:
            return "locator_not_found", None

        screenshot = await _screenshot_b64(loc)

        if field_name == "top_features":
            # Collect <li> children; fall back to splitlines
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
                raw = await loc.first.inner_text()
                lines = [_clean_text(line) for line in raw.splitlines() if _clean_text(line)]
                return lines, screenshot

        elif field_name == "add_to_cart":
            # Check visibility (button may exist but be hidden)
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
        return expected == found

    if field_name in ("selling_price", "original_price", "discount_percentage"):
        try:
            return abs(float(expected) - float(found)) < 0.01
        except (TypeError, ValueError):
            return False

    if field_name == "is_sellable":
        return bool(expected) == bool(found)

    return str(expected).strip().lower() == str(found).strip().lower()


# ── Field mapping ─────────────────────────────────────────────────────────────

FIELD_MAP = {
    "name": "name",
    "description": "description",
    "top_features": "top_features",
    "category": "category",
    "add_to_cart": "is_sellable",   # locator key → product field
    "selling_price": "selling_price",
    "original_price": "original_price",
    "discount_percentage": "discount_percentage",
}


# ── Stealth JS injected before every page ────────────────────────────────────

_STEALTH_JS = """
// Hide webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => false });

// Spoof plugins array
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Spoof languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});
"""


# ── Core scraping for one retailer ───────────────────────────────────────────

async def _scrape_retailer(page: Page, retailer: dict, product: Any) -> dict:
    """
    Navigate to a retailer URL and extract each specified locator field.
    Returns the result dict per the spec response shape.
    """
    url = retailer.get("url", "")
    platform = retailer.get("platform", "")
    locators: dict = retailer.get("locators", {})

    # Inject stealth JS before the page starts loading
    await page.add_init_script(_STEALTH_JS)

    try:
        # wait_until="networkidle" ensures Ajax/XHR settle before we query the DOM
        await page.goto(url, wait_until="networkidle", timeout=PAGE_TIMEOUT)
    except Exception:
        # networkidle can time out on pages with infinite polling; retry with load
        try:
            await page.goto(url, wait_until="load", timeout=PAGE_TIMEOUT)
        except Exception as e:
            return {
                "platform": platform,
                "url": url,
                "error": f"Failed to load page: {e}",
                "fields": {},
            }

    # Give JS frameworks (React/Angular/Vue) a moment to finish rendering
    await page.wait_for_timeout(SETTLE_MS)

    fields_result = {}

    for locator_key, css in locators.items():
        product_field = FIELD_MAP.get(locator_key, locator_key)

        # Determine expected value from product
        if locator_key == "add_to_cart":
            expected = getattr(product, "is_sellable", None)
        else:
            raw_expected = getattr(product, product_field, None)
            expected = float(raw_expected) if isinstance(raw_expected, Decimal) else raw_expected

        found, screenshot = await _extract_field(page, css, locator_key)

        if locator_key == "add_to_cart":
            match = _compare("is_sellable", expected, found)
            fields_result["is_sellable"] = {
                "expected": expected,
                "found": found,
                "match": match,
                "screenshot": screenshot,
            }
        else:
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
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            async def scrape_one(retailer: dict) -> dict:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 900},
                    # Pretend to be a real browser with common headers
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    },
                    java_script_enabled=True,
                    ignore_https_errors=True,
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
