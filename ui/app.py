import os
import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)
from dotenv import load_dotenv
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# Resolve .env from the project root (one level above this file's directory)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

app = Flask(__name__)
app.secret_key = os.urandom(32)
# x_prefix=1 reads X-Forwarded-Prefix from Nginx so url_for() generates
# correct URLs when the app is served under a sub-path
app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1)

APP_PASSWORD = os.getenv("APP_PASSWORD", "changeme")
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")


# ── Auth decorator ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == APP_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        else:
            error = "Incorrect password. Please try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html", fastapi_base_url=FASTAPI_BASE_URL)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
