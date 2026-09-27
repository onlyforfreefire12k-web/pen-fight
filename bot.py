"""Pen Fight Bot for Telegram.

Handlers:
    /start  -> short welcome message
    /game   -> a NORMAL URL button that opens the existing Pen Fight game.
               Works in private DMs, groups AND supergroups:
                   "/game"             -> answered in DM and in groups
                   "/game@MyBot"       -> answered (mention = this bot)
                   "/game@OtherBot"    -> ignored automatically

WHY A URL BUTTON (and not web_app=WebAppInfo):
    Telegram does NOT allow inline Web App buttons inside groups —
    Bot API rejects them with "BadRequest: Button_type_invalid".
    A normal URL button works everywhere (DM + group + supergroup).
    It is the same technique used by the working 3D Music Room bot.
    TIP: to open the game as a Mini App INSIDE Telegram (even from a
    group), set GAME_URL to your Mini App direct link:
        https://t.me/<bot_username>/<mini_app_short_name>?startapp=penfight
    With a plain HTTPS frontend URL it simply opens the website link.

The bot is started from live.py (see run_bot() / start_bot_thread() below).
"""

import asyncio
import logging
import threading

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
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

# Short group-friendly promo, identical in DM and in groups/supergroups.
GAME_TEXT = (
    "🖊️ <b>PEN FIGHT</b>\n\n"
    "Ready to play? Tap below to enter the game."
)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /start with a simple welcome message."""
    if update.message:
        await update.message.reply_text(WELCOME_TEXT, parse_mode="HTML")


async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /game with the launch button (DMs + groups + supergroups)."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🖊️ PLAY PEN FIGHT",
                    # NORMAL URL button — allowed in DM, groups, supergroups.
                    # (web_app=WebAppInfo buttons are REJECTED in groups with
                    #  "BadRequest: Button_type_invalid". Same approach as
                    #  the working 3D Music Room bot.)
                    url=GAME_URL,
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

    PYTHON 3.12 FIX (Render) — KEPT, DO NOT REMOVE:
    Python 3.12 no longer creates an event loop automatically in
    non-main threads, so asyncio.get_event_loop() — which
    run_polling() calls internally — raises:
        "RuntimeError: There is no current event loop in thread '…'"
    The fix is to create and set a fresh event loop for THIS thread
    before anything touches asyncio.
    """
    # --- Python 3.12 / Render event-loop fix (do this FIRST) -------------
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # ----------------------------------------------------------------------

    try:
        application = Application.builder().token(BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))

        # /game — registered normally, works in DMs AND groups/supergroups.
        # CommandHandler automatically accepts "/game" everywhere and
        # "/game@YourBot" when the mention matches this bot's username
        # ("/game@SomeOneElse" is ignored on purpose).
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
    finally:
        # run_polling(close_loop=True) normally closes the loop itself.
        # Only close here if an error happened before/while it started.
        if not loop.is_closed():
            loop.close()


def start_bot_thread() -> threading.Thread:
    """Start the bot's polling loop in a background daemon thread.

    Exactly ONE thread is ever created, so there is always exactly
    ONE polling instance running.
    """
    thread = threading.Thread(target=run_bot, name="pen-fight-bot", daemon=True)
    thread.start()
    return thread
