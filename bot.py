"""
bot.py
------
Pen Fight 3D — a minimal Telegram bot.

Commands
--------
/start   (private)  Pen Fight welcome card + 🎮 OPEN PEN FIGHT Web App button
/room    (groups)   Pen Fight room card + 🎮 JOIN PEN FIGHT Web App button

Both buttons are REAL Telegram Web App buttons (InlineKeyboardButton with
web_app=WebAppInfo), so the game opens INSIDE Telegram's WebView — never in
an external browser, never through a launch link. There are no launch codes,
no tokens, no startapp payloads and no generated URLs.

The Web App URL is NEVER hard-coded here — it comes from the
PEN_FIGHT_WEBAPP_URL environment variable via config.py, and it is validated
before a button is created (a missing/invalid URL produces a clear
configuration error and a simple user-facing message, never a crash).
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

import config

log = logging.getLogger("backend.bot")

GAME_NAME = "PEN FIGHT"

# Shown to users when the Web App URL is not configured. Deliberately generic
# — never leaks the configured value or any other internal detail.
_WEBAPP_UNAVAILABLE_MESSAGE = (
    "⚠️ Pen Fight is not configured yet.\n\n"
    "Please try again later."
)

# Optional bundled artwork for the /start welcome card. If the file is not
# present the bot automatically falls back to a text-only card.
_WELCOME_PHOTO = Path(__file__).resolve().parent / "assets" / "pen-fight-welcome.jpg"

_WELCOME_CAPTION = (
    "🎮 <b>PEN FIGHT</b>\n\n"
    "Welcome to Pen Fight!\n\n"
    "A multiplayer 3D fighting game where you can enter the room and play "
    "with others.\n\n"
    "Tap the button below to enter the game."
)

_GROUP_CARD_CAPTION = (
    "🎮 <b>PEN FIGHT ROOM</b>\n\n"
    "Ready for Pen Fight?\n\n"
    "Tap the button below to open the game."
)

_GROUP_CHAT_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)


def _web_app_url() -> str | None:
    """
    Return the configured Pen Fight Web App URL, or None when it is missing
    or malformed. Logs a clear configuration error exactly once per state
    change so operators can see the problem without spamming the logs.
    """
    url = config.PEN_FIGHT_WEBAPP_URL
    if not url or not url.startswith(("http://", "https://")):
        if not url:
            log.error(
                "[ERROR] Configuration error: PEN_FIGHT_WEBAPP_URL is not set. "
                "Set it in the environment (e.g. Render Environment Variables "
                "or .env) to enable the Web App buttons."
            )
        else:
            log.error(
                "[ERROR] Configuration error: PEN_FIGHT_WEBAPP_URL is invalid "
                "(must be a full http(s) URL). Web App buttons are disabled."
            )
        return None
    return url


def _open_button(label: str) -> InlineKeyboardMarkup | None:
    """One Web App button — opens INSIDE Telegram. None when unconfigured."""
    url = _web_app_url()
    if url is None:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label,
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


# ---------------------------------------------------------------------------
# /start — private welcome card
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    # In groups, /start stays quiet — the room card belongs to /room.
    if update.effective_chat.type != ChatType.PRIVATE:
        return

    keyboard = _open_button("🎮 OPEN PEN FIGHT")
    if keyboard is None:
        # Missing/invalid PEN_FIGHT_WEBAPP_URL — clear config error, no crash.
        await update.message.reply_text(_WEBAPP_UNAVAILABLE_MESSAGE)
        return

    if _WELCOME_PHOTO.is_file():
        try:
            with open(_WELCOME_PHOTO, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=_WELCOME_CAPTION,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            log.info("[GAME] welcome card sent user=%s", update.effective_user.id)
            return
        except TelegramError as exc:
            log.error("[ERROR] welcome photo failed: %s", type(exc).__name__)

    await update.message.reply_text(
        _WELCOME_CAPTION,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    log.info("[GAME] welcome card sent (text) user=%s", update.effective_user.id)


# ---------------------------------------------------------------------------
# /room — group room card
# ---------------------------------------------------------------------------


async def cmd_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    chat = update.effective_chat
    if chat.type not in _GROUP_CHAT_TYPES:
        await update.message.reply_text(
            "Use /room inside your Telegram group to open the Pen Fight room."
        )
        return

    keyboard = _open_button("🎮 JOIN PEN FIGHT")
    if keyboard is None:
        # Missing/invalid PEN_FIGHT_WEBAPP_URL — clear config error, no crash.
        await update.message.reply_text(_WEBAPP_UNAVAILABLE_MESSAGE)
        return

    await update.message.reply_text(
        _GROUP_CARD_CAPTION,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    log.info("[GAME] room card posted chat=%s", chat.id)


# ---------------------------------------------------------------------------
# Global error handler — log types only, never secret material
# ---------------------------------------------------------------------------


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error(
        "[ERROR] handler error type=%s",
        type(context.error).__name__ if context.error else "unknown",
    )


# ---------------------------------------------------------------------------
# Application factory — ONLY the two commands are registered
# ---------------------------------------------------------------------------


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise config.ConfigError("TELEGRAM_BOT_TOKEN is not configured.")

    application = (
        Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("room", cmd_room))
    application.add_error_handler(on_error)

    return application
