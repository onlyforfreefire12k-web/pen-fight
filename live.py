"""Entry point — run everything with: python live.py

1. Starts the userbot (Pyrogram MTProto) in a background thread.
2. Starts the PTB bot in a second background thread.
3. Starts Flask in the main thread (keeps Render alive).
"""

import logging

from flask import Flask, Response

from bot import start_bot_thread
from config import PORT
from userbot import start_userbot_thread

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
    # 1) Userbot thread (Pyrogram, MTProto)
    ub_thread = start_userbot_thread()
    logger.info("Userbot thread: %s", ub_thread.name)

    # 2) PTB bot thread
    bot_thread = start_bot_thread()
    logger.info("Bot thread: %s", bot_thread.name)

    # 3) Flask main thread
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
