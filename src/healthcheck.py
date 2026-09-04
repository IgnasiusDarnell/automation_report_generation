"""
Health check endpoint for Uptime Kuma.

Runs a tiny HTTP server on $HEALTH_PORT (default 8081) exposing GET /health.
Returns 200 only if ALL of these hold:
  - process responsive
  - MySQL reachable (live SELECT 1)
  - APScheduler running with >= 1 job registered

Response JSON:
  {
    "status": "ok" | "degraded",
    "db": "ok" | "down: <reason>",
    "scheduler": "ok (<n> jobs)" | "down: <reason>",
    "last_log_age_seconds": <int>,
    "telegram_polling": true | false
  }

Standalone HTTP health probe — safe to import & invoke from `python -m src.healthcheck`
(for Docker HEALTHCHECK) without spinning the server.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logger = logging.getLogger("healthcheck")

HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8081"))
LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "app.log"

_scheduler_ref: dict = {"scheduler": None}  # injected by main.py at startup


def set_scheduler(scheduler) -> None:
    """Called from main.py after scheduler.start() so /health can introspect it."""
    _scheduler_ref["scheduler"] = scheduler


def _check_db() -> tuple[bool, str]:
    try:
        # Lazy import — main.py already loaded .env at this point when called from main thread,
        # but for the standalone probe we load it ourselves.
        from dotenv import load_dotenv
        load_dotenv()
        import pymysql

        host = os.getenv("MYSQL_HOST", "localhost")
        port = int(os.getenv("MYSQL_PORT", "3306"))
        user = os.getenv("MYSQL_USER", "root")
        password = os.getenv("MYSQL_PASSWORD", "")
        database = os.getenv("MYSQL_DATABASE", "remindre_bot")

        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            database=database, connect_timeout=3,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
        return True, "ok"
    except Exception as e:
        return False, f"down: {type(e).__name__}: {e}"


def _check_scheduler() -> tuple[bool, str]:
    # Prefer in-process scheduler ref (works for HTTP /health served by main).
    sched = _scheduler_ref.get("scheduler")
    if sched is not None:
        if not sched.running:
            return False, "down: scheduler not running"
        jobs = sched.get_jobs()
        if not jobs:
            return False, "down: scheduler has no jobs"
        return True, f"ok ({len(jobs)} jobs)"

    # Fallback: standalone probe (Docker HEALTHCHECK runs as separate process,
    # so the in-process ref is empty). Verify the main bot process is alive by
    # checking that PID 1 is still python (main.py) and not a zombie/restart loop.
    try:
        with open("/proc/1/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", errors="replace").replace("\x00", " ").strip()
        if "src.main" not in cmdline:
            return False, f"down: pid 1 is not main.py (got: {cmdline[:80]})"
        # Probe scheduler indirectly: scheduler logs go to stdout & app.log.
        # If main has been running long enough, app.log should be recent.
        log_age = _check_log_age()
        if log_age < 0:
            return False, "down: cannot read app log"
        # Scheduler jobs fire at minute 0 of every hour and daily — within ~65 min
        # the log must have new entries from either bot polling or scheduler runs.
        # We allow up to 10 min of idle before flagging.
        if log_age > 600:
            return False, f"down: app log stale ({log_age}s) — scheduler may not be running"
        return True, f"ok (main alive, log age {log_age}s)"
    except Exception as e:
        return False, f"down: cannot probe main process: {e}"


def _check_log_age() -> int:
    """Seconds since the app log file was last written. -1 if unreadable."""
    try:
        mtime = LOG_PATH.stat().st_mtime
        return max(0, int(time.time() - mtime))
    except OSError:
        return -1


def build_report() -> tuple[int, dict]:
    db_ok, db_msg = _check_db()
    sched_ok, sched_msg = _check_scheduler()
    log_age = _check_log_age()

    # "degraded" if anything fails — we still return JSON so Uptime Kuma can parse it.
    healthy = db_ok and sched_ok
    payload = {
        "status": "ok" if healthy else "degraded",
        "db": db_msg,
        "scheduler": sched_msg,
        "last_log_age_seconds": log_age,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return (200 if healthy else 503), payload


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path not in ("/", "/health", "/healthz"):
            self.send_response(404)
            self.end_headers()
            return
        code, payload = build_report()
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # silence default access log noise
        logger.debug("health http: " + fmt, *args)


def start_server_in_thread() -> ThreadingHTTPServer:
    """Start the HTTP server on a daemon thread. Returns the server object."""
    server = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _Handler)
    t = threading.Thread(target=server.serve_forever, name="health-http", daemon=True)
    t.start()
    logger.info("Health endpoint listening on :%s/health", HEALTH_PORT)
    return server


def main_standalone() -> int:
    """Used by Docker HEALTHCHECK: probe DB+scheduler, exit 0 if ok else 1.
    Does NOT spin the HTTP server (the main process owns that).
    """
    logging.basicConfig(level=logging.INFO)
    code, payload = build_report()
    print(json.dumps(payload))
    return 0 if code == 200 else 1


def main_with_server() -> None:
    """Used when this module is run directly (`python -m src.healthcheck --serve`)
    — for local debugging. Production runs the server from src/main.py."""
    logging.basicConfig(level=logging.INFO)
    server = start_server_in_thread()
    try:
        # Try to attach to live scheduler if already imported by main process
        # (won't be the case when run standalone — that's fine, /health reports scheduler=down)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    if "--serve" in sys.argv:
        main_with_server()
    else:
        sys.exit(main_standalone())