"""Pen Fight Bot — commands + security layer.

Two clients run in this process:
  1. THIS PTB bot     — commands, Mini App button, login flow UI, moderation.
  2. Pyrogram userbot (userbot.py) — MTProto session for admin-level
     enforcement (demote/ban, VC kick). Runs in its own thread.

Authorization (from config.py / .env)
  • AUTH_USER_IDS — who may use security commands.
  • OWNER_ID is auto-included in AUTH_USER_IDS by config.py.
  • /game is PUBLIC — anyone can play, no auth needed.

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

import config
from config import (
    API_HASH,
    API_ID,
    AUTH_USER_IDS,
    BOT_TOKEN,
    MINI_APP_URL,
    OWNER_ID,
)
from database import db
from userbot import call_userbot, userbot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

if not AUTH_USER_IDS:
    logger.warning(
        "No authorized users found. Security commands disabled for everyone."
    )


def is_authorized(user_id: int | None) -> bool:
    return user_id is not None and user_id in AUTH_USER_IDS


# ---------------------------------------------------------------------------
# Texts / keyboards
# ---------------------------------------------------------------------------

NO_ACCESS_TEXT = (
    "🚫 <b>Access Denied</b>\n\n"
    "You don't have permission to use this bot.\n"
    "Contact the owner if you think this is a mistake."
)

WELCOME_TEXT = (
    "🎮 <b>Welcome to Pen Fight!</b> 🖊️\n\n"
    "Play the new INv Fight game in 3D.\n\n"
    "Use /game to start playing."
)

GAME_TEXT = "🖊️ <b>INV FIGHT</b>\n\nReady to play? Tap below to enter the game."


def _game_keyboard() -> InlineKeyboardMarkup:
    # NOTE: URL button (not web_app=) — Telegram rejects web_app in groups.
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("INV FIGHT FIGHT", url=MINI_APP_URL)]]
    )


# ---------------------------------------------------------------------------
# Filters — CHANNELS are always excluded
# ---------------------------------------------------------------------------

NOT_CHANNEL = ~filters.ChatType.CHANNEL
GROUPS_ONLY = filters.ChatType.GROUPS
PRIVATE_TEXT_NOCMD = filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND


def _is_dm(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE


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
    """DM: gate by auth. Group: short promo. Channel: ignored."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    chat_type = update.effective_chat.type

    # Group → short promo, no menu leak
    if chat_type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text(
            WELCOME_TEXT, parse_mode="HTML", reply_markup=_game_keyboard()
        )
        return

    # Channel → silently ignore
    if chat_type == ChatType.CHANNEL:
        return

    # DM → gate by auth
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return

    menu = (
        "🛡️ <b>Pen Fight Security</b>\n\n"
        "<b>Account</b>\n"
        "/login — connect your Telegram account\n"
        "/logout — disconnect your account\n"
        "/session — session status\n\n"
        "<b>Moderation</b> (reply to a user's message)\n"
        "/blacklist — block from groups & voice chats\n"
        "/unblacklist — remove from blacklist\n"
        "/trust — exempt an admin from auto-punish\n"
        "/untrust — remove exemption\n"
        "/gmute · /ungmute · /gmuteinfo — global mute\n\n"
        "<b>Reports</b>\n"
        "/security — security dashboard\n"
        "/logs — recent security events\n\n"
        "<b>Public</b>\n"
        "/game — play Pen Fight"
    )
    await update.message.reply_text(
        menu, parse_mode="HTML", reply_markup=_game_keyboard()
    )


# ---------------------------------------------------------------------------
# Login flow (DM only, authorized only)
# ---------------------------------------------------------------------------

_LOGIN_STATES: dict[int, dict] = {}


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_dm(update):
        await update.message.reply_text("🔒 /login only works in the bot's DM.")
        return
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return
    if not API_ID or not API_HASH:
        await update.message.reply_text(
            "⚙️ API_ID / API_HASH not set. Add them to .env first."
        )
        return

    user_id = update.effective_user.id
    if await db.get_session(user_id):
        await update.message.reply_text(
            "ℹ️ You already have an active session. Use /logout first."
        )
        return

    _LOGIN_STATES[user_id] = {"step": "phone"}
    await update.message.reply_text(
        "📱 <b>Login Started</b>\n\n"
        "Send your phone number in international format:\n"
        "<code>+1234567890</code>",
        parse_mode="HTML",
    )


async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not _is_dm(update):
        await update.message.reply_text("🔒 /logout only works in the bot's DM.")
        return
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return

    await update.message.reply_text("⏳ Logging out…")
    result = await call_userbot(userbot.logout(update.effective_user.id))
    await update.message.reply_text(result.get("message", "Done."))


async def session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return

    sess = await db.get_session(update.effective_user.id)
    if sess:
        await update.message.reply_text(
            "🔐 <b>Session</b>\n\n"
            "Status: 🟢 Connected\n"
            f"Phone: {sess.get('phone') or '—'}\n"
            f"Last used: {sess.get('last_used') or '—'}",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            "🔐 <b>Session</b>\n\nStatus: 🔴 Not connected\nUse /login to start.",
            parse_mode="HTML",
        )


async def login_flow_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle phone / OTP / 2FA while the user is in the login flow."""
    if not update.message or not update.effective_user or not update.message.text:
        return
    user_id = update.effective_user.id
    state = _LOGIN_STATES.get(user_id)
    if not state or not _is_dm(update):
        return

    text = update.message.text.strip()
    step = state["step"]

    # ---- phone ----
    if step == "phone":
        if not text.startswith("+"):
            await update.message.reply_text("❌ Use international format: +1234567890")
            return
        await update.message.reply_text("⏳ Sending verification code…")
        result = await call_userbot(userbot.login_start(text))

        if not result.get("success"):
            await update.message.reply_text(f"❌ {result.get('message')}")
            _LOGIN_STATES.pop(user_id, None)
            return

        state["phone"] = text
        state["phone_code_hash"] = result["phone_code_hash"]
        state["step"] = "code"
        await update.message.reply_text(
            "✅ Code sent to your Telegram account.\n"
            "Now send the code (e.g. <code>12345</code>).",
            parse_mode="HTML",
        )

    # ---- code ----
    elif step == "code":
        code = text.replace("-", "").replace(" ", "")
        await update.message.reply_text("⏳ Verifying code…")
        result = await call_userbot(
            userbot.login_complete(state["phone"], state["phone_code_hash"], code)
        )

        if result.get("success"):
            _LOGIN_STATES.pop(user_id, None)
            await update.message.reply_text(
                f"✅ {result.get('message')}\n\nUserbot monitoring is now ACTIVE."
            )
        elif result.get("needs_password"):
            try:
                await update.message.delete()
            except TelegramError:
                pass
            state["step"] = "password"
            state["code"] = code
            await update.message.reply_text(
                "🔐 <b>2FA enabled.</b>\nSend your password — I'll delete it instantly.",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(f"❌ {result.get('message')}")
            _LOGIN_STATES.pop(user_id, None)

    # ---- password (2FA) ----
    elif step == "password":
        try:
            await update.message.delete()
        except TelegramError:
            pass
        result = await call_userbot(
            userbot.login_complete(
                state["phone"],
                state["phone_code_hash"],
                state.get("code", ""),
                password=text,
            )
        )
        _LOGIN_STATES.pop(user_id, None)
        if result.get("success"):
            await update.message.reply_text(
                f"✅ {result.get('message')}\n\nUserbot monitoring is now ACTIVE."
            )
        else:
            await update.message.reply_text(f"❌ {result.get('message')}")


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
# Moderation commands (auth + groups + reply-based)
# ---------------------------------------------------------------------------

async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target or target.is_bot:
        await update.message.reply_text("Reply to a user's message with /blacklist.")
        return

    await db.add_blacklist(user_id=target.id, added_by=update.effective_user.id)
    await db.log(
        "BLACKLIST_ADD",
        severity="WARNING",
        actor_id=update.effective_user.id,
        target_id=target.id,
        chat_id=update.effective_chat.id,
    )
    await update.message.reply_text(
        f"🚫 {target.first_name} blacklisted.\n"
        "They will be muted/kicked from voice chats automatically."
    )


async def unblacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply to a user's message with /unblacklist.")
        return

    await db.remove_blacklist(target.id)
    await db.log(
        "BLACKLIST_REMOVE",
        actor_id=update.effective_user.id,
        target_id=target.id,
        chat_id=update.effective_chat.id,
    )
    await update.message.reply_text(f"✅ {target.first_name} removed from blacklist.")


async def trust_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply to a user's message with /trust.")
        return

    await db.add_trusted(target.id, update.effective_user.id)
    await db.log(
        "TRUST_ADD",
        actor_id=update.effective_user.id,
        target_id=target.id,
        chat_id=update.effective_chat.id,
    )
    await update.message.reply_text(
        f"🛡️ {target.first_name} trusted — exempt from auto-punish."
    )


async def untrust_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply to a user's message with /untrust.")
        return

    await db.remove_trusted(target.id)
    await db.log(
        "TRUST_REMOVE",
        actor_id=update.effective_user.id,
        target_id=target.id,
        chat_id=update.effective_chat.id,
    )
    await update.message.reply_text(f"✅ {target.first_name} is no longer trusted.")


# ---------------------------------------------------------------------------
# GMUTE (existing behaviour — JSON storage kept as-is)
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
    await db.log(
        "GMUTE_ADD", actor_id=update.effective_user.id, target_id=target.id
    )
    await update.message.reply_text("🔇 User has been globally muted.")


async def ungmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply with /ungmute.")
        return
    if target.id not in _global_muted:
        await update.message.reply_text("That user is not globally muted.")
        return

    _global_muted.discard(target.id)
    _save_gmuted()
    await db.log(
        "GMUTE_REMOVE", actor_id=update.effective_user.id, target_id=target.id
    )
    await update.message.reply_text("🔊 User has been globally unmuted.")


async def gmuteinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _deny_if_not_allowed(update):
        return
    target = _target_from_reply(update)
    if not target:
        await update.message.reply_text("Reply with /gmuteinfo.")
        return

    full_name = " ".join(p for p in (target.first_name, target.last_name) if p)
    username = f"@{target.username}" if target.username else "—"
    muted = target.id in _global_muted
    blacklisted = await db.is_blacklisted(target.id)
    trusted = await db.is_trusted(target.id)

    await update.message.reply_text(
        "🛡️ <b>USER INFO</b>\n\n"
        f"Name: {full_name}\n"
        f"Username: {username}\n"
        f"User ID: <code>{target.id}</code>\n"
        f"GMute: {'🔇 muted' if muted else '🔊 not muted'}\n"
        f"Blacklist: {'🚫 yes' if blacklisted else '✅ no'}\n"
        f"Trusted: {'🛡️ yes' if trusted else '❌ no'}",
        parse_mode="HTML",
    )


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
# Info commands
# ---------------------------------------------------------------------------

async def security_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return

    sess = await db.get_session(OWNER_ID) if OWNER_ID else None
    groups = await db.list_groups()
    blacklist = await db.list_blacklist()

    account = "🟢 Connected" if sess else "🔴 Not connected"
    userbot_status = "🟢 RUNNING" if userbot.is_running else "🔴 STOPPED"

    await update.message.reply_text(
        "🛡️ <b>SECURITY STATUS</b>\n\n"
        f"Userbot: {userbot_status}\n"
        f"Account: {account}\n"
        f"Monitored groups: {len(groups)}\n"
        f"Blacklisted users: {len(blacklist)}\n"
        f"Globally muted: {len(_global_muted)}\n\n"
        f"Abuse rule: {config.ABUSE_THRESHOLD} removals / "
        f"{config.ABUSE_WINDOW_SECONDS}s\n"
        f"Authorized users: {len(AUTH_USER_IDS)}",
        parse_mode="HTML",
    )


async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text(NO_ACCESS_TEXT, parse_mode="HTML")
        return

    events = await db.recent_logs(limit=10)
    if not events:
        await update.message.reply_text("ℹ️ No security events yet.")
        return

    emoji = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨", "ERROR": "❌"}
    lines = ["📋 <b>RECENT SECURITY EVENTS</b>\n"]
    for ev in events:
        e = emoji.get(ev.get("severity", "INFO"), "ℹ️")
        lines.append(
            f"{e} <b>{ev['event_type']}</b>\n"
            f"  actor: {ev.get('actor_id') or '—'} · "
            f"target: {ev.get('target_id') or '—'}\n"
            f"  {ev.get('timestamp')}\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


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

        # ---- login (DM only, enforced inside handlers too) ----
        application.add_handler(
            CommandHandler("login", login_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("logout", logout_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("session", session_command, filters=NOT_CHANNEL)
        )

        # ---- moderation ----
        application.add_handler(
            CommandHandler("blacklist", blacklist_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("unblacklist", unblacklist_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("trust", trust_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("untrust", untrust_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("gmute", gmute_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("ungmute", ungmute_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("gmuteinfo", gmuteinfo_command, filters=NOT_CHANNEL)
        )

        # ---- info ----
        application.add_handler(
            CommandHandler("security", security_command, filters=NOT_CHANNEL)
        )
        application.add_handler(
            CommandHandler("logs", logs_command, filters=NOT_CHANNEL)
        )

        # ---- group 1: login flow (DM text) + gmute watcher (groups) ----
        application.add_handler(
            MessageHandler(PRIVATE_TEXT_NOCMD, login_flow_message), group=1
        )
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
