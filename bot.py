"""Pen Fight Bot for Telegram.

Handlers:
    /start      -> short welcome message
    /game       -> Mini App launch button (DM + groups + supergroups)
    /gmute      -> globally mute a user (reply to their message, auth users only)
    /ungmute    -> remove a global mute (reply to their message, auth users only)
    /gmuteinfo  -> show a user's global mute status (reply, auth users only)

Plus a group message watcher that auto-deletes every message sent by a
globally muted user, in EVERY group/supergroup where this bot is admin.

WHY URL BUTTONS (and not web_app=WebAppInfo):
    Telegram does NOT allow inline Web App buttons inside groups —
    Bot API rejects them with "400 Bad Request: Button_type_invalid".
    A normal URL button works everywhere (DM + group + supergroup).
    Pointing that URL at the Mini App direct link
    (https://t.me/<bot>/<short_name>) opens the game INSIDE Telegram
    as a Mini App — the same technique used by the 3D Music Room bot.

The bot is started from live.py (see run_bot() / start_bot_thread() below).
"""

import asyncio
import json
import logging
import os
import threading

from telegram import (
    Chat,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pen Fight Mini App
# ---------------------------------------------------------------------------

# Official Mini App direct link (configured in BotFather):
#   bot:        @Penfightgamebot
#   short name: penfight
#   web app:    https://node-static-3fe2b.wasmer.app/
MINI_APP_URL = "https://t.me/Penfightgamebot/penfight"

# ---------------------------------------------------------------------------
# Authorized users (GMUTE)
# ---------------------------------------------------------------------------
# Only these Telegram user IDs may use /gmute, /ungmute and /gmuteinfo.
# Set AUTH_USER_IDS in your environment as a comma-separated list of numeric IDs,
# e.g. AUTH_USER_IDS=123456789,987654321
AUTH_USER_IDS = {
    int(uid.strip())
    for uid in os.environ.get("AUTH_USER_IDS", "").split(",")
    if uid.strip().isdigit()
}

if not AUTH_USER_IDS:
    logger.warning(
        "AUTH_USER_IDS is empty — /gmute, /ungmute, /gmuteinfo are DISABLED for everyone."
    )

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
# GMUTE — global mute storage (persistent file + in-memory cache)
# ---------------------------------------------------------------------------
#
# This backend project has NO database (Firebase belongs to the Pen Fight
# game frontend, untouched per spec), so the smallest possible persistent
# solution is a tiny JSON file. The muted user IDs are cached in a set in
# memory, so the per-message delete check is a pure O(1) lookup with NO
# disk/network request. The file is only touched on /gmute and /ungmute.
#
# If you later want cross-instance persistence (e.g. Firebase), only
# _load_gmuted() / _save_gmuted() need to change — nothing else.

GMUTE_FILE = "gmute_users.json"

# In-memory cache: {telegram_user_id, ...} — checked on every group message.
_global_muted: set[int] = set()


def _load_gmuted() -> set[int]:
    """Load muted user IDs from disk. Never crashes the bot."""
    try:
        if os.path.exists(GMUTE_FILE):
            with open(GMUTE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return {int(uid) for uid in data}
    except (OSError, ValueError) as exc:
        logger.error("Could not load %s: %s", GMUTE_FILE, exc)
    return set()


def _save_gmuted() -> None:
    """Persist the current muted set. Never crashes the bot."""
    try:
        with open(GMUTE_FILE, "w", encoding="utf-8") as fh:
            json.dump(sorted(_global_muted), fh)
    except OSError as exc:
        logger.error("Could not save %s: %s", GMUTE_FILE, exc)


# Load once at startup — survives restarts/redeploys via the JSON file.
_global_muted = _load_gmuted()
logger.info("GMUTE: loaded %d globally muted user(s).", len(_global_muted))


def _is_auth_user(update: Update) -> bool:
    """True only if the command sender is in the AUTH_USER_IDS whitelist."""
    user = update.effective_user
    if not user:
        return False
    return user.id in AUTH_USER_IDS


async def _sender_is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True only if the command sender is an admin of the CURRENT group.

    Normal members can NOT use /gmute, /ungmute or /gmuteinfo.
    """
    user = update.effective_user
    chat = update.effective_chat
    if not (user and chat):
        return False
    if chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        return False
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
    except TelegramError as exc:
        logger.warning("get_chat_member failed in %s: %s", chat.id, exc)
        return False
    status = getattr(member.status, "value", member.status)
    return status in ("administrator", "creator")


def _target_from_reply(update: Update):
    """Get the actual telegram.User from the REPLIED-TO message.

    Uses the real Telegram user_id — never trusted username text.
    Returns None when there is no reply or no from_user.
    """
    message = update.message
    if not message or not message.reply_to_message:
        return None
    return message.reply_to_message.from_user


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /start with a simple welcome message."""
    if update.message:
        await update.message.reply_text(WELCOME_TEXT, parse_mode="HTML")


async def game_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /game with the Mini App launch button (DM + groups)."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🖊️ PLAY PEN FIGHT",
                    # NORMAL URL button -> Pen Fight Mini App direct link.
                    url=MINI_APP_URL,
                )
            ]
        ]
    )

    if update.message:
        await update.message.reply_text(
            GAME_TEXT, parse_mode="HTML", reply_markup=keyboard
        )


async def gmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/gmute (reply to a user's message) — globally mute them, auth users only."""
    message = update.message
    if not message or not message.chat:
        return

    if message.chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("This command only works in groups.")
        return

    if not _is_auth_user(update):
        await message.reply_text("⛔ Only authorized users can use this command.")
        return

    target = _target_from_reply(update)
    if target is None:
        await message.reply_text("Reply to a user's message with /gmute to mute them globally.")
        return

    if target.id == context.bot.id:
        await message.reply_text("I can't globally mute myself.")
        return

    if target.id in _global_muted:
        await message.reply_text("That user is already globally muted.")
        return

    _global_muted.add(target.id)
    _save_gmuted()
    logger.info("GMUTE: %s muted globally (total %d).", target.id, len(_global_muted))
    await message.reply_text("🔇 User has been globally muted.")


async def ungmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ungmute (reply to a user's message) — remove global mute, auth users only."""
    message = update.message
    if not message or not message.chat:
        return

    if message.chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("This command only works in groups.")
        return

    if not _is_auth_user(update):
        await message.reply_text("⛔ Only authorized users can use this command.")
        return

    target = _target_from_reply(update)
    if target is None:
        await message.reply_text("Reply to a user's message with /ungmute to unmute them.")
        return

    if target.id not in _global_muted:
        await message.reply_text("That user is not globally muted.")
        return

    _global_muted.discard(target.id)
    _save_gmuted()
    logger.info("GMUTE: %s unmuted globally (total %d).", target.id, len(_global_muted))
    await message.reply_text("🔊 User has been globally unmuted.")


async def gmuteinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/gmuteinfo (reply to a user's message) — show mute status, auth users only."""
    message = update.message
    if not message or not message.chat:
        return

    if message.chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
        await message.reply_text("This command only works in groups.")
        return

    if not _is_auth_user(update):
        await message.reply_text("⛔ Only authorized users can use this command.")
        return

    target = _target_from_reply(update)
    if target is None:
        await message.reply_text("Reply to a user's message with /gmuteinfo.")
        return

    full_name = " ".join(part for part in (target.first_name, target.last_name) if part)
    username = f"@{target.username}" if target.username else "—"
    muted = target.id in _global_muted
    status = "🔇 GLOBALLY MUTED" if muted else "🔊 not muted"

    await message.reply_text(
        "🛡 GMUTE INFO\n\n"
        f"Name: {full_name}\n"
        f"Username: {username}\n"
        f"User ID: {target.id}\n"
        f"Status: {status}"
    )


# ---------------------------------------------------------------------------
# GMUTE watcher — auto-delete messages from globally muted users
# ---------------------------------------------------------------------------

async def gmute_watcher(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete every message sent by a globally muted user, in ANY group.

    Runs AFTER command handlers (separate handler group), is triggered by
    all normal user messages (text, photos, videos, documents, stickers,
    GIFs/animations, voice, audio, video notes, edited messages, ...).

    The mute check is an O(1) in-memory set lookup — no disk/network I/O.
    Never replies, never warns, never crashes the bot.
    """
    message = update.effective_message
    if message is None:
        return

    user = message.from_user
    if user is None or user.is_bot:
        # channel posts / anonymous senders / service messages / our own bot
        return

    if user.id not in _global_muted:
        return

    try:
        await message.delete()
    except TelegramError as exc:
        # Bot not admin here, message already gone, or older than 48h —
        # ignore and keep the bot running.
        logger.debug(
            "GMUTE delete failed (chat %s, msg %s): %s",
            message.chat_id,
            message.message_id,
            exc,
        )


# All normal user messages in groups/supergroups, EXCLUDING service messages
# (joins/leaves, pins, topic changes — never touch those).
GMUTE_MSG_FILTER = (
    filters.ALL
    & ~filters.StatusUpdate.ALL
    & filters.ChatType.GROUPS
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

        # --- Existing commands (UNCHANGED) ---
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("game", game_command))

        # --- GMUTE commands (auth users only) ---
        # CommandHandler automatically accepts "/gmute" and
        # "/gmute@YourBot" (mention must match this bot's username).
        application.add_handler(CommandHandler("gmute", gmute_command))
        application.add_handler(CommandHandler("ungmute", ungmute_command))
        application.add_handler(CommandHandler("gmuteinfo", gmuteinfo_command))

        # --- GMUTE watcher (default group 0 handles commands first,
        # this watcher runs in group 1 afterwards for every message) ---
        application.add_handler(MessageHandler(GMUTE_MSG_FILTER, gmute_watcher), group=1)

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
