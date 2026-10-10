"""Configuration loader for the Pen Fight Bot."""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Bot basics
# ---------------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
GAME_URL = os.getenv("GAME_URL")
PORT = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# Mini App button — URL that the /game button opens
# ---------------------------------------------------------------------------
MINI_APP_URL = os.getenv(
    "MINI_APP_URL", "https://t.me/Penfightgamebot/penfight"
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
if not BOT_TOKEN:
    raise RuntimeError("[config] BOT_TOKEN missing. Add it to .env")

if not GAME_URL:
    raise RuntimeError("[config] GAME_URL missing. Add it to .env")

_parsed = urlparse(GAME_URL)
if _parsed.scheme != "https" or not _parsed.netloc:
    raise RuntimeError(f"[config] GAME_URL invalid: {GAME_URL!r}")

if not MINI_APP_URL.startswith("https://t.me/"):
    raise RuntimeError(
        "[config] MINI_APP_URL must look like "
        "https://t.me/<bot_username>/<short_name>"
    )
