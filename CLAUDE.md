# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A full-stack product data integrity verification system. It scrapes product data (name, description, price, features, etc.) from e-commerce retailer websites using Playwright and compares the scraped results against expected values stored in a MySQL database.

## Architecture

Two separate services:

- **FastAPI backend** (`api/`) — REST API on port 8100. Handles product CRUD and web scraping/sync operations. Interactive docs at `http://localhost:8100/docs`.
- **Flask UI** (`ui/`) — Simple dashboard on port 5000 with password authentication. The single Jinja2 template (`ui/templates/index.html`) loads Vue.js 3 and Tailwind CSS from CDN — no build step. `FASTAPI_BASE_URL` is injected as a Jinja2 template variable and used by the Vue.js app to call the API directly.

The scraper (`api/services/scraper.py`) is the core of the system. It uses Playwright for async browser automation. Per-retailer configuration (CSS selectors, browser type, headers, proxies, viewport) lives in `api/configs/browser_configs.json`. Each product in the DB has a `retailers` JSON field containing an array of retailer objects with URLs and field locators.

Database: MySQL via SQLAlchemy ORM (`mysql+pymysql` driver). Migrations managed by Alembic.

There are no automated tests in this project.

## Running the Services

```bash
# Activate virtual environment
source venv/bin/activate

# Start FastAPI backend (port 8100)
uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload

# Start Flask UI (port 5000) — separate terminal
python ui/app.py
```

## Environment

Copy `.env.example` to `.env` and configure:
```
APP_PASSWORD=...           # Flask UI login password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
FASTAPI_BASE_URL=http://localhost:8100
```

## Database Migrations

```bash
# Apply all migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "description"
```

## Key API Endpoints

- `GET /health` — health check
- `GET|POST /api/products` — list / create products
- `PUT|DELETE /api/products/{id}` — update / delete
- `POST /api/sync/run/{id}` — scrape a single product
- `POST /api/sync/run` — scrape all products (batches of 3)

## Product Data Model

The `products` table columns: `name`, `description`, `top_features` (JSON array of strings), `category`, `is_live` (bool), `is_sellable` (bool), `selling_price`, `original_price`, `discount_percentage`, `retailers` (JSON).

The `retailers` field is a JSON array of objects. Each object must have at minimum:
```json
{ "platform": "Kohls", "url": "https://..." }
```
`platform` must match a key in `browser_configs.json` (falls back to `"default"` if not found).

## Scraper internals

**Locator keys** in `browser_configs.json` map to product fields via `FIELD_MAP` in `scraper.py`:
- `name` → `name`, `description` → `description`, `top_features` → `top_features`, `category` → `category`
- `add_to_cart` → `is_sellable` (checks element visibility, compared against `product.is_sellable`)
- `selling_price` / `original_price` / `discount_percentage` → numeric fields (parsed as float)

**Tunable constants** at the top of `api/services/scraper.py`:
- `ELEMENT_TIMEOUT` (default 8000 ms) — per-element wait
- `PAGE_TIMEOUT` (default 20000 ms) — initial page load
- `SETTLE_MS` (default 3000 ms) — post-load JS settle delay

**Stealth** is opt-in per retailer via `"stealth": true` in `browser_configs.json`. It injects JS that patches `navigator.webdriver`, plugins, languages, `window.chrome`, and the Permissions API.

**Browser grouping**: retailers sharing the same `browser_type` reuse a single browser instance per `scrape_product` call. Launch options come from the first retailer in each group. A new browser context is created per retailer within the group (contexts are not shared).

**Page load strategy**: Pages wait for `domcontentloaded`, then sleep `SETTLE_MS` for JS frameworks to render. Extra headers and proxy settings apply at the context level.

**Field extraction**: When an element is not found within `ELEMENT_TIMEOUT`, `_extract_field()` returns the magic string `"locator_not_found"` (not an exception). Check for this value when debugging missing fields. Feature (`top_features`) extraction tries `<li>` elements first, then falls back to `splitlines()`.

**Comparison logic**:
- Prices: float delta `< 0.01` (epsilon comparison)
- Strings (`name`, `description`, `category`): case-insensitive, whitespace-stripped
- `top_features`: exact list equality
- `is_sellable`: checks visibility of the `add_to_cart` element

**Screenshots**: Both per-element and full-page screenshots are captured as base64-encoded PNGs and included in sync results. Screenshot failures are silent (returns `None`).

**Sync batching**: `POST /api/sync/run` processes products in batches of 3. Products *within* a batch are scraped in parallel via `asyncio.gather()`; batches run sequentially.

## Adding a New Retailer

1. Add a new entry in `api/configs/browser_configs.json` with the retailer's name as the key. Configure `browser_type`, `launch_options`, `context_options`, `locators` (CSS selectors per field), and optionally `extra_headers`, `proxy`, `stealth`, and `delay_before_nav_ms`.
2. Add retailer objects (with `platform` matching the new key) to individual products via the UI or API.

`retailers.json` at the project root is a standalone reference file showing example retailer objects with per-product CSS selector overrides (distinct from the global `browser_configs.json` selectors).

## Notes

- The Flask `secret_key` is regenerated on every restart (`os.urandom(32)`), so all sessions are invalidated on server restart.
- `playwright-stealth` is listed in `requirements.txt` but is **not imported** anywhere. Stealth behaviour is implemented via the custom `_STEALTH_JS` string injected with `page.add_init_script()` in `scraper.py`.

## Dependencies

Install: `pip install -r requirements.txt`
Playwright browser: `playwright install chromium`
