"""Pen Fight Bot — /game only.

Single PTB bot client in this thread:
  • /start and /game — PUBLIC, anyone can play, no auth needed.
  • /game shows 3 buttons: PEN ARENA + DRAW & DROP + SNAKE & LADDERS.

Chat scope
  • PRIVATE chats + GROUPS (public + private) → handled.
  • CHANNELS → completely ignored.
"""

import asyncio
import logging
import threading

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, DRAW_DROP_URL, MINI_APP_URL, SNAKE_LADDERS_URL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Texts / keyboards
# ---------------------------------------------------------------------------

WELCOME_TEXT = (
    "🎮 <b>Welcome to Pen Fight!</b> 🖊️\n\n"
    "Play the new Pen Fight game in 3D.\n\n"
    "Use /game to start playing."
)

GAME_TEXT = (
    "🖊️ <b>Pen FIGHT</b>\n\n"
    "Choose a game below and start playing."
)


def _game_keyboard() -> InlineKeyboardMarkup:
    # NOTE: URL buttons (not web_app=) — Telegram rejects web_app in groups.
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("PEN ARENA", url=MINI_APP_URL)],
            [InlineKeyboardButton("DRAW & DROP", url=DRAW_DROP_URL)],
            [InlineKeyboardButton("SNAKE & LADDERS", url=SNAKE_LADDERS_URL)],
        ]
    )


# ---------------------------------------------------------------------------
# Filters — CHANNELS are always excluded
# ---------------------------------------------------------------------------

NOT_CHANNEL = ~filters.ChatType.CHANNEL


# ---------------------------------------------------------------------------
# PUBLIC commands (NO auth)
# ---------------------------------------------------------------------------

async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Public — anyone, anywhere (DM or group)."""
    if update.message:
        await update.message.reply_text(
            GAME_TEXT, parse_mode="HTML", reply_markup=_game_keyboard()
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """DM or group → game promo. Channel → ignored."""
    if not update.message or not update.effective_chat:
        return

    # Channel → silently ignore
    if update.effective_chat.type == ChatType.CHANNEL:
        return

    await update.message.reply_text(
        WELCOME_TEXT, parse_mode="HTML", reply_markup=_game_keyboard()
    )


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Update error: %s", context.error, exc_info=context.error)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def run_bot() -> None:
    """Build PTB Application and start long polling (background thread)."""
    # Python 3.12 / Render fix — create loop for THIS thread first
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        application = Application.builder().token(BOT_TOKEN).build()

        # ---- public ----
        application.add_handler(
            CommandHandler("game", game_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("start", start_command, filters=NOT_CHANNEL)
        )

        application.add_error_handler(error_handler)

        logger.info("PTB bot started — polling…")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            stop_signals=None,        # we are NOT in the main thread
        )

    except InvalidToken:
        logger.error("Invalid BOT_TOKEN.")
    except TelegramError as exc:
        logger.error("Telegram API error: %s", exc, exc_info=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("Bot crashed: %s", exc, exc_info=True)
        raise
    finally:
        if not loop.is_closed():
            loop.close()


def start_bot_thread() -> threading.Thread:
    t = threading.Thread(target=run_bot, name="pen-fight-bot", daemon=True)
    t.start()
    return t
