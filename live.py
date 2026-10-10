"""Entry point — run everything with: python live.py

1. Starts the PTB bot in a background thread (/start + /game only).
2. Starts Flask in the main thread (keeps Render alive).
"""

import logging

from flask import Flask, Response

from bot import start_bot_thread
from config import PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("live")

app = Flask(__name__)


@app.route("/", methods=["GET"])
def index() -> Response:
    return Response("Pen Fight Bot is running.", mimetype="text/plain")


@app.route("/health", methods=["GET"])
def health() -> Response:
    return Response("OK", mimetype="text/plain")


def main() -> None:
    # 1) PTB bot thread (/start + /game)
    bot_thread = start_bot_thread()
    logger.info("Bot thread: %s", bot_thread.name)

    # 2) Flask main thread
    try:
        logger.info("Flask health server on 0.0.0.0:%s", PORT)
        app.run(host="0.0.0.0", port=PORT)
    except OSError as exc:
        logger.error("Flask port %s busy: %s", PORT, exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Flask crashed: %s", exc, exc_info=True)
        raise


if __name__ == "__main__":
    main()
