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
# Game buttons — URLs that the /game buttons open
# ---------------------------------------------------------------------------
# Pen Fight (main game)
MINI_APP_URL = os.getenv(
    "MINI_APP_URL", "https://t.me/Penfightgamebot/Penfight"
)

# Draw & Drop (second game)
DRAW_DROP_URL = os.getenv(
    "DRAW_DROP_URL", "https://t.me/Penfightgamebot/drawanddrop"
)

# Snake & Ladders (third game)
SNAKE_LADDERS_URL = os.getenv(
    "SNAKE_LADDERS_URL", "https://t.me/Penfightgamebot/snakeandladders"
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

if not DRAW_DROP_URL.startswith("https://"):
    raise RuntimeError(
        "[config] DRAW_DROP_URL must be a valid https URL "
        "(t.me mini app link or website link)"
    )

if not SNAKE_LADDERS_URL.startswith("https://"):
    raise RuntimeError(
        "[config] SNAKE_LADDERS_URL must be a valid https URL "
        "(t.me mini app link or website link)"
    )
