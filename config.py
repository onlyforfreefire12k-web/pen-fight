import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GAME_WEBAPP_URL = os.getenv("GAME_WEBAPP_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
