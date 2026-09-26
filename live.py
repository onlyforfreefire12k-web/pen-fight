"""
live.py
-------
Production entry point — `python live.py`

Runs BOTH processes together in one dyno/web-service:

1. The Telegram bot (long polling, python-telegram-bot) — main thread.
2. The Flask HTTP server (health endpoints) — daemon thread bound to
   0.0.0.0:$PORT so Render's health checks pass.

No gunicorn — Flask's server is exactly what Render needs here because the
HTTP surface is only health checks.

Endpoints
---------
GET  /        -> "3D Room Backend Online"
GET  /health  -> {"status": "ok", "service": "3d-room-backend"}
"""

from __future__ import annotations

import logging
import threading

from flask import Flask, jsonify

import config

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("backend.live")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    return "3D Room Backend Online"


@app.get("/health")
def health():
    # Must stay lightweight and dependency-free — Render probes this.
    return jsonify({"status": "ok", "service": "3d-room-backend"}), 200


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


def _run_flask() -> None:
    log.info("[LIVE] Flask listening on 0.0.0.0:%s", config.PORT)
    app.run(
        host="0.0.0.0",
        port=config.PORT,
        threaded=True,
        use_reloader=False,
        debug=False,
    )


def main() -> None:
    config.validate_or_raise()

    import bot as bot_module

    application = bot_module.build_application()

    flask_thread = threading.Thread(
        target=_run_flask, name="flask-health-server", daemon=True
    )
    flask_thread.start()

    log.info("[LIVE] Pen Fight bot starting (long polling)…")
    # run_polling manages its own asyncio loop and signal handlers; it must
    # run on the main thread. drop_pending_updates skips stale updates after
    # restarts.
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
