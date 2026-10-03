"""Configuration loader for the Pen Fight Bot."""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GAME_URL = os.getenv("GAME_URL")
PORT = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# Userbot (MTProto) — for /login, admin abuse detection, VC blacklist
# Get API_ID / API_HASH from https://my.telegram.org → API Development Tools
# ---------------------------------------------------------------------------
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")

# Your personal Telegram user ID — only this ID may /login
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)

# ---------------------------------------------------------------------------
# Security engine
# ---------------------------------------------------------------------------
SESSION_DB = os.getenv("SESSION_DB", "penfight.db")

# Sliding window: if an admin bans N users within T seconds → auto-punish
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

if API_ID and not API_HASH:
    raise RuntimeError("[config] API_HASH missing (API_ID set).")
if API_HASH and not API_ID:
    raise RuntimeError("[config] API_ID missing (API_HASH set).")
