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
# Default matches your current Mini App direct link.
# ---------------------------------------------------------------------------
MINI_APP_URL = os.getenv(
    "MINI_APP_URL", "https://t.me/Penfightgamebot/penfight"
)

# ---------------------------------------------------------------------------
# Userbot (MTProto)
# ---------------------------------------------------------------------------
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")

# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
# OWNER_ID       → main owner (userbot session + owner alerts)
# AUTH_USER_IDS  → list of numeric ids allowed to use the bot
#                  (owner is auto-included)
# ---------------------------------------------------------------------------
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

AUTH_USER_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("AUTH_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
if OWNER_ID:
    AUTH_USER_IDS.add(OWNER_ID)

# ---------------------------------------------------------------------------
# Security engine
# ---------------------------------------------------------------------------
SESSION_DB = os.getenv("SESSION_DB", "penfight.db")
ABUSE_WINDOW_SECONDS = int(os.getenv("ABUSE_WINDOW_SECONDS", "60"))
ABUSE_THRESHOLD = int(os.getenv("ABUSE_THRESHOLD", "5"))

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

if API_ID and not API_HASH:
    raise RuntimeError("[config] API_HASH missing (API_ID set).")
if API_HASH and not API_ID:
    raise RuntimeError("[config] API_ID missing (API_HASH set).")

if not OWNER_ID:
    raise RuntimeError("[config] OWNER_ID missing. Add your Telegram user id.")
