"""Entry point — run everything with:  python live.py

1. Starts the Telegram bot in a background thread (see bot.py).
2. Starts a lightweight Flask server in the main thread, which keeps
   hosting platforms (Render, Railway, ...) alive and provides
   health endpoints:

       GET /        -> "Pen Fight Bot is running."
       GET /health  -> "OK"

No gunicorn, no Docker, no external commands required.
"""

import logging

from flask import Flask, Response

from bot import start_bot_thread
from config import PORT

# Single logging configuration for the whole process
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("live")

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index() -> Response:
    """Simple liveness page for humans."""
    return Response("Pen Fight Bot is running.", mimetype="text/plain")


@app.route("/health", methods=["GET"])
def health() -> Response:
    """Health endpoint for Render / uptime monitors."""
    return Response("OK", mimetype="text/plain")


def main() -> None:
    # 1) Start the bot — one single polling thread, ever.
    bot_thread = start_bot_thread()
    logger.info("Bot thread started: %s", bot_thread.name)

    # 2) Start Flask in the MAIN thread (blocking call).
    try:
        logger.info("Flask health server listening on 0.0.0.0:%s", PORT)
        app.run(host="0.0.0.0", port=PORT)
    except OSError as exc:
        logger.error(
            "Flask could not start on port %s — already in use? (%s)", PORT, exc
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Flask crashed unexpectedly: %s", exc, exc_info=True)
        raise


if __name__ == "__main__":
    main()
