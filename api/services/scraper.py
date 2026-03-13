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
ELEMENT_TIMEOUT = 8000

# How long (ms) to wait for the initial page DOM
PAGE_TIMEOUT = 20000

# Extra settle time (ms) after DOM connects — gives JS frameworks time to mount
SETTLE_MS = 3000


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


import json
import os

# ── Config Loading ────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "browser_configs.json")

def _get_browser_config(platform: str) -> dict:
    try:
        with open(CONFIG_PATH, "r") as f:
            configs = json.load(f)
        return configs.get(platform, configs.get("default", {}))
    except Exception:
        # Fallback to a safe default if file missing or corrupt
        return {
            "browser_type": "chromium",
            "launch_options": {"headless": True},
            "context_options": {"java_script_enabled": True}
        }

# ── Selective stealth injection (disabled by default as modern CDNs detect it) ──
_STEALTH_JS = ""

# ── Core scraping for one retailer ───────────────────────────────────────────

async def _scrape_retailer(page: Page, retailer: dict, product: Any) -> dict:
    """
    Navigate to a retailer URL and extract each specified locator field.
    """
    url = retailer.get("url", "")
    platform = retailer.get("platform", "")
    config = _get_browser_config(platform)
    locators: dict = config.get("locators", {})

    # Added a delay to simulate human dwell time if specified in config
    delay_ms = config.get("delay_before_nav_ms", 0)
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
    except Exception as e:
        return {
            "platform": platform,
            "url": url,
            "error": f"Failed to load page: {e}",
            "fields": {},
        }

    # Give JS frameworks time to finish rendering
    await page.wait_for_timeout(SETTLE_MS)

    fields_result = {}

    for locator_key, css in locators.items():
        product_field = FIELD_MAP.get(locator_key, locator_key)

        if locator_key == "add_to_cart":
            expected = getattr(product, "is_sellable", None)
        else:
            raw_expected = getattr(product, product_field, None)
            expected = float(raw_expected) if isinstance(raw_expected, Decimal) else raw_expected

        if css is None:
            found, screenshot = "locator_not_found", None
        else:
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

    try:
        full_page_screenshot_bytes = await page.screenshot(type="png", full_page=True)
        full_page_screenshot = base64.b64encode(full_page_screenshot_bytes).decode("utf-8")
    except Exception:
        full_page_screenshot = None

    return {
        "platform": platform,
        "url": url,
        "full_page_screenshot": full_page_screenshot,
        "fields": fields_result,
    }

# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_product(product: Any) -> dict:
    """
    Scrape all retailers for a single product. 
    Grouped by browser type to optimize resource usage while respecting per-site needs.
    """
    retailers = product.retailers or []
    retailer_results = []

    # Map browser_type -> [retailers]
    groups = {}
    for r in retailers:
        platform = r.get("platform", "")
        config = _get_browser_config(platform)
        b_type = config.get("browser_type", "chromium")
        if b_type not in groups:
            groups[b_type] = []
        groups[b_type].append((r, config))

    async with async_playwright() as pw:
        for b_type, items in groups.items():
            browser_launcher = getattr(pw, b_type)
            # Take launch options from the first retailer in the group
            # (In practice, retailers in a group should share launch options)
            launch_options = items[0][1].get("launch_options", {})
            
            browser = await browser_launcher.launch(**launch_options)
            try:
                for r, config in items:
                    context_options = config.get("context_options", {})
                    extra_headers = config.get("extra_headers", {})
                    
                    context = await browser.new_context(**context_options, extra_http_headers=extra_headers)
                    try:
                        page = await context.new_page()
                        res = await _scrape_retailer(page, r, product)
                        retailer_results.append(res)
                    finally:
                        await context.close()
            finally:
                await browser.close()

    return {
        "product_id": product.id,
        "product_name": product.name,
        "retailers": retailer_results,
    }
