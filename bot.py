"""Pen Fight Bot for Telegram.

Handlers:
    /start  -> short welcome message
    /game   -> promo message + a Telegram Web App button that opens the
               existing Pen Fight game INSIDE Telegram (not a browser).

The bot is started from live.py (see run_bot() / start_bot_thread() below).
"""

import logging
import threading

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import BOT_TOKEN, GAME_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

WELCOME_TEXT = (
    "🎮 <b>Welcome to Pen Fight!</b> 🖊️\n\n"
    "Play the classic childhood Pen Fight game in 3D.\n\n"
    "Use /game to start playing."
)

GAME_TEXT = (
    "🎮 <b>PEN FIGHT</b>\n\n"
    "🖊️ Classic childhood Pen Fight — now in 3D!\n\n"
    "⚔️ Play against bots\n"
    "🏆 Earn coins\n"
    "🛍️ Collect different pens\n"
    "🌐 Multiplayer rooms\n\n"
    "Tap the button below to play inside Telegram 👇"
)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /start with a simple welcome message."""
    if update.message:
        await update.message.reply_text(WELCOME_TEXT, parse_mode="HTML")


async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /game with the promo text and the Web App launch button."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🖊️ PLAY PEN FIGHT",
                    # web_app=... is what opens the game INSIDE Telegram
                    # instead of a normal external browser URL:
                    web_app=WebAppInfo(url=GAME_URL),
                )
            ]
        ]
    )

    if update.message:
        await update.message.reply_text(
            GAME_TEXT, parse_mode="HTML", reply_markup=keyboard
        )


# ---------------------------------------------------------------------------
# Error handling — never fail silently
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every Telegram API / handler error instead of crashing silently."""
    logger.error(
        "Error while processing an update: %s",
        context.error,
        exc_info=context.error,
    )


# ---------------------------------------------------------------------------
# Bot startup (called from live.py)
# ---------------------------------------------------------------------------

def run_bot() -> None:
    """Build the Application and start long polling.

    Designed to run inside a background thread next to Flask:
    stop_signals=None is mandatory because signal handlers are only
    allowed in the main thread. This avoids event-loop / signal
    conflicts between Flask and python-telegram-bot.
    """
    try:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("game", game_command))
        application.add_error_handler(error_handler)

        logger.info("Telegram bot started — polling for updates…")
        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
            stop_signals=None,  # we are NOT in the main thread
        )
    except InvalidToken:
        logger.error(
            "Invalid BOT_TOKEN — check the token from @BotFather in your .env file."
        )
    except TelegramError as exc:
        logger.error("Telegram API error: %s", exc, exc_info=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("Bot crashed unexpectedly: %s", exc, exc_info=True)
        raise


def start_bot_thread() -> threading.Thread:
    """Start the bot's polling loop in a background daemon thread.

    Exactly ONE thread is ever created, so there is always exactly
    ONE polling instance running.
    """
    thread = threading.Thread(target=run_bot, name="pen-fight-bot", daemon=True)
    thread.start()
    return thread
