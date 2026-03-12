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

## 4. Install Playwright Browser

```bash
playwright install chromium
# or, if using the venv:
venv/bin/playwright install chromium
```

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

Copy `.env` and fill in your values:

```env
APP_PASSWORD=your_secret_password   # password for the web UI login
DB_HOST=localhost
DB_PORT=3306
DB_NAME=product_checker
DB_USER=root
DB_PASSWORD=your_db_password
FASTAPI_BASE_URL=http://localhost:8100   # change port if needed
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

## 8. Start the FastAPI Backend

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload
# or with venv:
venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8100 --reload
```

API will be available at: `http://localhost:8100`

> **Note:** The port must match `FASTAPI_BASE_URL` in `.env`.

---

## 9. Start the Flask UI Server

Open a **second terminal** and run:

```bash
python ui/app.py
# or with venv:
venv/bin/python ui/app.py
```

UI will be available at: `http://localhost:5000`

---

## 10. Open the App

1. Navigate to [http://localhost:5000](http://localhost:5000)
2. Enter your `APP_PASSWORD` from `.env`
3. You're in!

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
├── .env                   # Environment config
├── alembic.ini
└── requirements.txt
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `alembic: command not found` | Use `venv/bin/alembic` or add `~/.local/bin` to PATH |
| `Address already in use` | Run `fuser -k 5000/tcp` or `fuser -k 8100/tcp` |
| `products` table not created | Run `alembic revision --autogenerate -m "init"` then `alembic upgrade head` |
| Playwright download timeout | Re-run `playwright install chromium` (retries automatically) |
| Login not working | Check `APP_PASSWORD` in `.env` matches what you type |
