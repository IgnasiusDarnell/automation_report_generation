"""Web admin GUI untuk KOMPU Report Automation Bot.

Service ini berjalan terpisah dari bot Telegram tapi share image Docker yang sama
(butuh LibreOffice untuk konversi DOCX -> PDF saat re-generate laporan).

Fitur:
  - Login single-admin (username/password dari .env, di-hash Werkzeug).
  - CRUD user Telegram (display_name, telegram_chat_id, role, categories, active).
  - Monitoring per user: log harian per bulan, foto per bulan, statistik.
  - Edit & hapus log dari web.
  - Re-generate laporan bulanan (DOCX + PDF) on-demand.

Jalankan lokal (debug):
  python -m src.web.app
Jalankan via Docker:
  docker-compose up remindre-web
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash

# Agar 'from src...' bisa resolve apakah web dijalankan sebagai module atau langsung
BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.db.mysql_db import MySQLDB  # noqa: E402

# ---------------------------- Setup ----------------------------

load_dotenv(BASE_DIR / ".env")

(BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "logs" / "web.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("web")

WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "automation_darma")
# Saat container start, kalau ada plain-text password di .env, hash dulu lalu pakai hash itu
_raw_pw = os.getenv("ADMIN_PASSWORD", "")
if _raw_pw:
    ADMIN_PASSWORD_HASH = generate_password_hash(_raw_pw)
    logger.info("ADMIN_PASSWORD di-hash pada startup.")
else:
    # Fallback: anggap .env sudah berisi hash Werkzeug
    ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
    if not ADMIN_PASSWORD_HASH:
        logger.critical("ADMIN_PASSWORD / ADMIN_PASSWORD_HASH kosong. Web tidak bisa login.")
SECRET_KEY = os.getenv("WEB_SECRET_KEY") or "dev-only-change-me"

try:
    db = MySQLDB()
except Exception as e:
    logger.critical(f"Gagal inisialisasi MySQLDB: {e}")
    db = None


# ---------------------------- App ----------------------------

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "src" / "web" / "templates"),
    static_folder=str(BASE_DIR / "src" / "web" / "static"),
)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,  # 8 jam
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)
# Pastikan folder static ada
(BASE_DIR / "src" / "web" / "static").mkdir(parents=True, exist_ok=True)


# ---------------------------- Helpers ----------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_year_month() -> str:
    return datetime.now().strftime("%Y-%m")


def parse_categories(raw: str) -> list:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def month_stats_for_user(user_id: str, year_month: str) -> dict:
    """Hitung statistik cepat untuk 1 user pada 1 bulan."""
    logs = db.get_logs_by_month(user_id, year_month)
    images = db.get_images_for_user_month(user_id, year_month)
    by_cat: dict = {}
    by_status: dict = {}
    for l in logs:
        cat = l.get("category") or "(Tanpa Kategori)"
        by_cat[cat] = by_cat.get(cat, 0) + 1
        st = l.get("status") or "(Tanpa Status)"
        by_status[st] = by_status.get(st, 0) + 1
    return {
        "log_count": len(logs),
        "image_count": len(images),
        "by_category": by_cat,
        "by_status": by_status,
    }


# ---------------------------- Routes: auth ----------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == ADMIN_USERNAME and ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin_logged_in"] = True
            session["admin_username"] = username
            session.permanent = True
            logger.info(f"Admin login OK: {username}")
            return redirect(request.args.get("next") or url_for("dashboard"))
        logger.warning(f"Admin login gagal untuk username='{username}'")
        flash("Username atau password salah.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Anda telah logout.", "info")
    return redirect(url_for("login"))


# ---------------------------- Routes: dashboard ----------------------------

@app.route("/")
@login_required
def dashboard():
    users = db.get_all_users() if db else []
    ym = current_year_month()
    summary = []
    for u in users:
        stats = month_stats_for_user(u["user_id"], ym) if u.get("active") else {
            "log_count": 0, "image_count": 0, "by_category": {}, "by_status": {}
        }
        summary.append({**u, "stats": stats})
    return render_template(
        "dashboard.html",
        users=summary,
        year_month=ym,
        admin_username=session.get("admin_username", ""),
    )


# ---------------------------- Routes: users CRUD ----------------------------

@app.route("/users")
@login_required
def users_list():
    users = db.get_all_users() if db else []
    return render_template("users_list.html", users=users)


@app.route("/users/new", methods=["GET", "POST"])
@login_required
def users_new():
    if request.method == "POST":
        data = {
            "user_id": request.form.get("user_id", "").strip(),
            "display_name": request.form.get("display_name", "").strip(),
            "full_name": request.form.get("full_name", "").strip(),
            "name_upper": request.form.get("name_upper", "").strip(),
            "role": request.form.get("role", "").strip(),
            "placement": request.form.get("placement", "").strip() or "KOMPU",
            "area": request.form.get("area", "").strip() or "Politeknik Pekerjaan Umum",
            "telegram_chat_id": request.form.get("telegram_chat_id", "").strip(),
            "template": request.form.get("template", "").strip(),
            "categories": parse_categories(request.form.get("categories", "")),
            "active": request.form.get("active") == "on",
        }
        if not data["user_id"] or not data["display_name"]:
            flash("user_id dan display_name wajib diisi.", "danger")
        else:
            ok, msg = db.create_user(data, actor=session.get("admin_username", "ADMIN"))
            flash(msg, "success" if ok else "danger")
            if ok:
                return redirect(url_for("users_list"))
        return render_template("user_form.html", user=data, mode="new")
    return render_template("user_form.html", user={}, mode="new")


@app.route("/users/<user_id>")
@login_required
def users_detail(user_id: str):
    user = db.get_user_by_user_id(user_id)
    if not user:
        flash(f"User '{user_id}' tidak ditemukan.", "danger")
        return redirect(url_for("users_list"))
    ym = request.args.get("year_month", current_year_month())
    logs = db.get_logs_by_month(user_id, ym)
    images = db.get_images_for_user_month(user_id, ym)
    stats = month_stats_for_user(user_id, ym)
    return render_template(
        "user_detail.html",
        user=user,
        logs=logs,
        images=images,
        stats=stats,
        year_month=ym,
    )


@app.route("/users/<user_id>/edit", methods=["GET", "POST"])
@login_required
def users_edit(user_id: str):
    user = db.get_user_by_user_id(user_id)
    if not user:
        flash(f"User '{user_id}' tidak ditemukan.", "danger")
        return redirect(url_for("users_list"))
    if request.method == "POST":
        data = {
            "display_name": request.form.get("display_name", "").strip(),
            "full_name": request.form.get("full_name", "").strip(),
            "name_upper": request.form.get("name_upper", "").strip(),
            "role": request.form.get("role", "").strip(),
            "placement": request.form.get("placement", "").strip(),
            "area": request.form.get("area", "").strip(),
            "telegram_chat_id": request.form.get("telegram_chat_id", "").strip(),
            "template": request.form.get("template", "").strip(),
            "categories": parse_categories(request.form.get("categories", "")),
            "active": request.form.get("active") == "on",
        }
        ok, msg = db.update_user(user_id, data, actor=session.get("admin_username", "ADMIN"))
        flash(msg, "success" if ok else "danger")
        if ok:
            return redirect(url_for("users_detail", user_id=user_id))
        user.update({k: v for k, v in data.items() if k != "active"})
        user["active"] = data["active"]
    user["categories_str"] = ", ".join(user.get("categories") or [])
    return render_template("user_form.html", user=user, mode="edit")


@app.route("/users/<user_id>/delete", methods=["POST"])
@login_required
def users_delete(user_id: str):
    ok, msg = db.delete_user(user_id, actor=session.get("admin_username", "ADMIN"))
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("users_list"))


# ---------------------------- Routes: log edit/delete ----------------------------

@app.route("/logs/<log_id>/edit", methods=["GET", "POST"])
@login_required
def logs_edit(log_id: str):
    log = db.get_log_by_log_id(log_id)
    if not log:
        flash(f"Log '{log_id}' tidak ditemukan.", "danger")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        data = {
            "raw_text": request.form.get("raw_text", ""),
            "final_text": request.form.get("final_text", ""),
            "category": request.form.get("category", "").strip(),
            "status": request.form.get("status", "APPROVED"),
        }
        ok, msg = db.update_log(log_id, data, actor=session.get("admin_username", "ADMIN"))
        flash(msg, "success" if ok else "danger")
        if ok:
            return redirect(url_for("users_detail", user_id=log["user_id"],
                                    year_month=log.get("year_month", current_year_month())))
    return render_template("log_edit.html", log=log)


@app.route("/logs/<log_id>/delete", methods=["POST"])
@login_required
def logs_delete(log_id: str):
    log = db.get_log_by_log_id(log_id)
    if not log:
        flash("Log tidak ditemukan.", "danger")
        return redirect(url_for("dashboard"))
    ok, msg = db.delete_log(log_id, actor=session.get("admin_username", "ADMIN"))
    flash(msg, "success" if ok else "danger")
    return redirect(url_for("users_detail", user_id=log["user_id"],
                            year_month=log.get("year_month", current_year_month())))


# ---------------------------- Routes: re-generate report ----------------------------

@app.route("/users/<user_id>/regenerate", methods=["POST"])
@login_required
def users_regenerate(user_id: str):
    user = db.get_user_by_user_id(user_id)
    if not user:
        flash("User tidak ditemukan.", "danger")
        return redirect(url_for("users_list"))
    ym = request.form.get("year_month", current_year_month())
    fmt = request.form.get("format", "both")  # "docx" | "pdf" | "both"
    try:
        from src.reports.generator import ReportGenerator
        report_gen = ReportGenerator(db)
        docx_path, pdf_path = report_gen.generate(user_id, ym)
        flash(f"Laporan {ym} untuk {user_id} berhasil di-generate.", "success")
        # Sajikan halaman detail dengan link download
        return redirect(url_for("users_detail", user_id=user_id, year_month=ym,
                                generated_docx=os.path.basename(docx_path),
                                generated_pdf=os.path.basename(pdf_path) if pdf_path else ""))
    except Exception as e:
        logger.exception(f"Gagal regenerate laporan {user_id}/{ym}: {e}")
        flash(f"Gagal generate laporan: {e}", "danger")
        return redirect(url_for("users_detail", user_id=user_id, year_month=ym))


@app.route("/download/<path:filename>")
@login_required
def download(filename: str):
    # Hanya izinkan download dari storage/output
    safe_root = (BASE_DIR / "storage" / "output").resolve()
    target = (safe_root / filename).resolve()
    if not str(target).startswith(str(safe_root)) or not target.is_file():
        abort(404)
    return send_file(str(target), as_attachment=True)


# ---------------------------- Routes: health ----------------------------

@app.route("/health")
def health():
    if db is None:
        return {"status": "down", "reason": "db not initialized"}, 503
    try:
        users = db.get_all_users()
        return {"status": "ok", "users": len(users)}
    except Exception as e:
        return {"status": "down", "reason": str(e)}, 503


# ---------------------------- Main ----------------------------

if __name__ == "__main__":
    logger.info(f"Web GUI starting on http://{WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)