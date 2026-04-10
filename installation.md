# Installation Guide — Product Data Integrity Checker

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| MySQL | 8.0+ |
| pip | latest |

---

## 1. Clone / Download the Project

```bash
cd /path/to/your/workspace
# Place the project files here
```

---

## 2. Create a Virtual Environment (Recommended)

```bash
python3 -m venv venv
source venv/bin/activate   # Linux / macOS
# venv\Scripts\activate    # Windows
```

---

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Install Playwright Browsers

Two browsers are required based on the retailer configurations in `api/configs/browser_configs.json`:

| Browser | Used by |
|---|---|
| `chromium` | Default, DSW |
| `webkit` | Kohls (mobile Safari rendering) |

```bash
playwright install chromium webkit
# or, if using the venv:
venv/bin/playwright install chromium webkit
```

On Linux, each browser also requires system-level dependencies. Install them with:

```bash
playwright install-deps
# or, if using the venv:
venv/bin/playwright install-deps
```

> **Note:** If you add a new retailer that uses `"browser_type": "firefox"`, run `playwright install firefox` and `playwright install-deps firefox` as well.

---

## 5. Create the MySQL Database

Log in to MySQL and run:

```sql
CREATE DATABASE product_checker
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

---

## 6. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
APP_PASSWORD=your_secret_password   # password for the web UI login
DB_HOST=127.0.0.1                   # use 127.0.0.1, not localhost, to force TCP connection
DB_PORT=3306
DB_NAME=product_checker
DB_USER=root
DB_PASSWORD=your_db_password
FASTAPI_BASE_URL=http://localhost:8100   # on a server, set this to the public URL (see Production section)
```

---

## 7. Run Database Migrations

```bash
# From the project root:
alembic upgrade head
# or with venv:
venv/bin/alembic upgrade head
```

This creates the `products` table. You should see:
```
INFO  Running upgrade  -> <hash>, create_products_table
```

---

## 8. Start the Services (Local Development)

```bash
# Terminal 1 — FastAPI backend
uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload

# Terminal 2 — Flask UI
python ui/app.py
```

- API available at: `http://localhost:8100` — interactive docs at `http://localhost:8100/docs`
- UI available at: `http://localhost:5000`

---

## 9. Open the App

1. Navigate to `http://localhost:5000`
2. Enter your `APP_PASSWORD` from `.env`
3. You're in!

---

## Production Deployment (Ubuntu Server + Nginx)

### Install PM2

PM2 keeps both services running and restarts them automatically on crash or reboot.

```bash
# Install Node.js (required for PM2)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

### Start Services with PM2

Both services must bind to `127.0.0.1` so they are only reachable through Nginx.

```bash
cd /path/to/project

pm2 start "venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8100" \
  --name "product-checker-backend"

pm2 start "venv/bin/python ui/app.py" \
  --name "product-checker-frontend"

# Persist across reboots
pm2 save
pm2 startup   # run the command it prints
```

Common PM2 commands:

```bash
pm2 status
pm2 restart product-checker-backend
pm2 logs product-checker-frontend --lines 50
```

### Update `.env` for Production

`FASTAPI_BASE_URL` is injected into the Vue.js frontend and called directly from the user's browser — it must be the public URL, not `localhost`:

```env
FASTAPI_BASE_URL=https://yourdomain.com/your-sub-path
```

Then restart the frontend to pick up the change:

```bash
pm2 restart product-checker-frontend
```

### Nginx Configuration

Add the following `location` blocks inside your existing `server {}` block for your domain. The API block must appear before the UI catch-all block.

```nginx
# -------- Product Checker — Backend (FastAPI) --------
location /your-sub-path/api/ {
    proxy_pass         http://127.0.0.1:8100/api/;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout    300s;   # sync-all can run for several minutes
    proxy_connect_timeout 10s;
}

# -------- Product Checker — Frontend (Flask UI) --------
location /your-sub-path/ {
    proxy_pass         http://127.0.0.1:5000/;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    # Tells Flask's ProxyFix what prefix was stripped, so redirects
    # (login → index, logout → login) generate correct URLs
    proxy_set_header   X-Forwarded-Prefix /your-sub-path;
}
```

> Replace `/your-sub-path` with your actual path (e.g. `/ai-agents/ecommerce-product-checker`).
> The trailing slash on both `location` and `proxy_pass` is required — without it Nginx will not strip the prefix before forwarding to Flask.

Reload Nginx after editing:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## Directory Structure

```
/
├── api/                   # FastAPI backend
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── routers/
│   │   ├── products.py    # CRUD endpoints
│   │   └── sync.py        # Crawl endpoints
│   ├── services/
│   │   └── scraper.py     # Playwright scraper
│   └── alembic/           # DB migrations
├── ui/                    # Flask UI server
│   ├── app.py
│   └── templates/
│       ├── login.html
│       └── index.html
├── .env                   # Environment config (copy from .env.example)
├── alembic.ini
└── requirements.txt
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `alembic: command not found` | Use `venv/bin/alembic` or add `~/.local/bin` to PATH |
| `Temporary failure in name resolution` on `alembic upgrade head` | Set `DB_HOST=127.0.0.1` in `.env` (not a hostname) |
| `Address already in use` | Run `fuser -k 5000/tcp` or `fuser -k 8100/tcp` |
| `products` table not created | Run `alembic revision --autogenerate -m "init"` then `alembic upgrade head` |
| Playwright download timeout | Re-run `playwright install chromium webkit` |
| Nginx returns 404 for the sub-path | Ensure trailing slashes on both `location` and `proxy_pass` in Nginx config |
| Login redirect goes to wrong URL | Ensure `X-Forwarded-Prefix` header is set in the Nginx Flask location block |
| Login not working | Check `APP_PASSWORD` in `.env` matches what you type |
| Port 5000 publicly accessible | Flask must bind to `127.0.0.1`, not `0.0.0.0` — check `ui/app.py` |
