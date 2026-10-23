"""Pen Fight Bot — /game + gmute.

Single PTB bot client in this thread:
  • /start and /game — PUBLIC, anyone can play, no auth needed.
  • /game shows 3 buttons: PEN ARENA + DRAW & DROP + SNAKE & LADDERS.
  • /gmute, /gunmute (alias /ungmute) — AUTH USERS only, reply-based.

Chat scope
  • PRIVATE chats + GROUPS (public + private) → handled.
  • CHANNELS → completely ignored.
"""

import asyncio
import json
import logging
import os
import threading

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    AUTH_USER_IDS,
    BOT_TOKEN,
    DRAW_DROP_URL,
    MINI_APP_URL,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

if not AUTH_USER_IDS:
    logger.warning(
        "No authorized users found. /gmute commands disabled for everyone."
    )


def is_authorized(user_id: int | None) -> bool:
    return user_id is not None and user_id in AUTH_USER_IDS


# ---------------------------------------------------------------------------
# Texts / keyboards
# ---------------------------------------------------------------------------

NO_ACCESS_TEXT = (
    "🚫 <b>Access Denied</b>\n\n"
    "You don't have permission to use this command.\n"
    "Contact the owner if you think this is a mistake."
)

WELCOME_TEXT = (
    "🎮 <b>Welcome to GAME HUB!</b> 🖊️\n\n"
    "Play the new  games in 3D.\n\n"
    "Use /game to start playing."
)

GAME_TEXT = (
    "🖊️ <b>GAME HUB</b>\n\n"
    "Choose a game below and start playing."
)


def _game_keyboard() -> InlineKeyboardMarkup:
    # NOTE: URL buttons (not web_app=) — Telegram rejects web_app in groups.
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("3D FAIR", url=MINI_APP_URL)],
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
# Moderation helpers
# ---------------------------------------------------------------------------

def _target_from_reply(update: Update):
    msg = update.message
    if not msg or not msg.reply_to_message:
        return None
    return msg.reply_to_message.from_user


async def _deny_if_not_allowed(update: Update) -> bool:
    """Return True if the caller is NOT allowed (already replied)."""
    if not update.message or not update.effective_user:
        return True
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return True
    chat = update.effective_chat
    if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text(
            "⚠️ This command only works in groups. Reply to a user's message."
        )
        return True
    return False


# ---------------------------------------------------------------------------
# GMUTE — auth-only, JSON storage
# ---------------------------------------------------------------------------

GMUTE_FILE = "gmute_users.json"
_global_muted: set[int] = set()


def _load_gmuted() -> set[int]:
    try:
        if os.path.exists(GMUTE_FILE):
            with open(GMUTE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return {int(u) for u in data}
    except (OSError, ValueError) as exc:
        logger.error("Could not load %s: %s", GMUTE_FILE, exc)
    return set()


def _save_gmuted() -> None:
    try:
        with open(GMUTE_FILE, "w", encoding="utf-8") as fh:
            json.dump(sorted(_global_muted), fh)
    except OSError as exc:
        logger.error("Could not save %s: %s", GMUTE_FILE, exc)


_global_muted = _load_gmuted()
logger.info("GMUTE: loaded %d globally muted user(s).", len(_global_muted))


async def gmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auth-only. Reply to a user's message in a group."""
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply with /gmute to mute globally.")
        return
    if target.id == context.bot.id:
        await update.message.reply_text("I can't globally mute myself.")
        return
    if target.id in _global_muted:
        await update.message.reply_text("That user is already globally muted.")
        return

    _global_muted.add(target.id)
    _save_gmuted()
    await update.message.reply_text("🔇 User has been globally muted.")


async def gunmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auth-only. Serves both /gunmute and /ungmute."""
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply with /gunmute to unmute.")
        return
    if target.id not in _global_muted:
        await update.message.reply_text("That user is not globally muted.")
        return

    _global_muted.discard(target.id)
    _save_gmuted()
    await update.message.reply_text("🔊 User has been globally unmuted.")


# ---------------------------------------------------------------------------
# GMUTE watcher (group=1, runs after commands in group=0)
# ---------------------------------------------------------------------------

async def gmute_watcher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    user = message.from_user
    if user is None or user.is_bot:
        return
    if user.id not in _global_muted:
        return
    try:
        await message.delete()
    except TelegramError as exc:
        logger.debug(
            "GMUTE delete failed chat=%s msg=%s: %s",
            message.chat_id, message.message_id, exc,
        )


GMUTE_MSG_FILTER = (
    filters.ALL & ~filters.StatusUpdate.ALL & filters.ChatType.GROUPS
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

        # ---- gmute (auth enforced inside handlers) ----
        application.add_handler(
            CommandHandler("gmute", gmute_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("ungmute", gunmute_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("gunmute", gunmute_command, filters=NOT_CHANNEL)
        )

        # ---- group 1: gmute watcher ----
        application.add_handler(
            MessageHandler(GMUTE_MSG_FILTER, gmute_watcher), group=1
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
