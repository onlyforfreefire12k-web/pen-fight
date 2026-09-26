"""Configuration loader for the Pen Fight Bot.

All secrets and environment-specific values live in the .env file
(never in the source code). Copy .env.example to .env and fill it in.
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ

BOT_TOKEN = os.getenv("BOT_TOKEN")
GAME_URL = os.getenv("GAME_URL")
PORT = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# Validation — fail loudly at startup, not silently at runtime
# ---------------------------------------------------------------------------

if not BOT_TOKEN:
    raise RuntimeError(
        "[config] BOT_TOKEN is missing.\n"
        "         Create a .env file and add:\n"
        "         BOT_TOKEN=123456:your-token-from-BotFather"
    )

if not GAME_URL:
    raise RuntimeError(
        "[config] GAME_URL is missing.\n"
        "         Add it to your .env file:\n"
        "         GAME_URL=https://your-deployed-pen-fight-game.com"
    )

_parsed_url = urlparse(GAME_URL)
if _parsed_url.scheme != "https" or not _parsed_url.netloc:
    raise RuntimeError(
        f"[config] GAME_URL looks invalid: {GAME_URL!r}\n"
        "         Telegram Web Apps require a public HTTPS URL,\n"
        "         e.g. https://pen-fight.onrender.com"
    )
