import os
import threading

from flask import Flask

from bot import create_bot


app = Flask(__name__)


@app.get("/")
def home():
    return "Pen Fight Bot is running."


@app.get("/health")
def health():
    return {"status": "ok"}


def run_bot():
    bot = create_bot()
    bot.run_polling()


if __name__ == "__main__":
    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True
    )
    bot_thread.start()

    port = int(os.getenv("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port
    )
