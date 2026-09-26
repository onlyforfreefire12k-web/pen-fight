"""
bot.py
------
Pen Fight 3D — a minimal Telegram bot.

Commands
--------
/start   (private)  Pen Fight welcome +  🎮 OPEN PEN FIGHT  Web App button
/room    (groups)   Pen Fight room  +  🎮 JOIN PEN FIGHT  Web App button

Both buttons are REAL Telegram Web App buttons (InlineKeyboardButton with
web_app=WebAppInfo), so the game opens INSIDE Telegram's WebView — never in
an external browser, never through a launch link. No launch codes, no tokens,
no startapp payloads, no generated URLs.

The Web App URL is NEVER hard-coded — it comes from the PEN_FIGHT_WEBAPP_URL
environment variable via config.py and is validated (must be https://) before
any button is created. When it is missing/invalid the bot logs a clear
configuration error and replies with a simple message — it never crashes.

Every Telegram error path logs the REAL Telegram API message (str(exc) with a
traceback), so a 400 Bad Request reveals its actual reason instead of hiding
behind type(exc).__name__.
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
from telegram.constants import ChatType
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

import config

log = logging.getLogger("backend.bot")

GAME_NAME = "PEN FIGHT"

# Shown when the Web App URL is not usable. Generic on purpose — it must not
# leak the configured value or any internal detail.
_WEBAPP_NOT_CONFIGURED = "❌ Pen Fight Web App is not configured."

# Optional bundled artwork for the /start welcome message. When the file is
# absent or the send fails, we fall back to a single plain-text message.
_WELCOME_PHOTO = Path(__file__).resolve().parent / "assets" / "pen-fight-welcome.jpg"

_WELCOME_MESSAGE = (
    "🎮 PEN FIGHT\n\n"
    "Welcome to Pen Fight!\n\n"
    "A multiplayer 3D fighting game where you can enter the room and play "
    "with others.\n\n"
    "Tap the button below to enter the game."
)

_GROUP_CARD_MESSAGE = (
    "🎮 PEN FIGHT ROOM\n\n"
    "Ready to play Pen Fight?\n\n"
    "Tap the button below to enter the game."
)

_PRIVATE_ROOM_MESSAGE = "Use /room inside your Telegram group to open Pen Fight."

_GROUP_CHAT_TYPES = (ChatType.GROUP, ChatType.SUPERGROUP)


def _web_app_url() -> str | None:
    """
    Return the configured Web App URL, or None when unusable.

    Telegram only accepts https URLs for Web App buttons and rejects anything
    else with `400 Bad Request: BUTTON_WEBAPP_INFO_INVALID` — so we validate
    BEFORE building the button and log a clear line telling the operator what
    is wrong (instead of letting Telegram answer 400 later).
    """
    url = (config.PEN_FIGHT_WEBAPP_URL or "").strip()
    if not url:
        log.error("[ERROR] PEN_FIGHT_WEBAPP_URL is missing")
        return None
    if not url.startswith("https://"):
        log.error(
            "[ERROR] PEN_FIGHT_WEBAPP_URL must start with https:// "
            "(Telegram Web App buttons require HTTPS)"
        )
        return None
    return url


def _pen_fight_markup(button_label: str) -> InlineKeyboardMarkup | None:
    """Build the single Web App button, or None when the URL is unconfigured."""
    url = _web_app_url()
    if url is None:
        return None
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    button_label,
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


async def _reply(message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Send a text reply; a BadRequest inside it surfaces with its message."""
    try:
        await message.reply_text(text, reply_markup=markup)
    except TelegramError as exc:
        log.error(
            "[ERROR] failed to send message to chat %s: %s",
            getattr(getattr(message, "chat", None), "id", "?"),
            str(exc),
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# /start — private welcome
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        # In groups, /start stays quiet — the room card belongs to /room.
        return

    if not config.PEN_FIGHT_WEBAPP_URL:
        log.error("[ERROR] PEN_FIGHT_WEBAPP_URL is missing")
        await update.message.reply_text(_WEBAPP_NOT_CONFIGURED)
        return

    markup = _pen_fight_markup("🎮 OPEN PEN FIGHT")
    if markup is None:
        await update.message.reply_text(_WEBAPP_NOT_CONFIGURED)
        return

    # Try the artwork card first; on ANY failure send ONE text fallback.
    sent_photo = False
    if _WELCOME_PHOTO.is_file():
        try:
            with open(_WELCOME_PHOTO, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=_WELCOME_MESSAGE,
                    reply_markup=markup,
                )
            sent_photo = True
        except (TelegramError, OSError) as exc:
            log.error(
                "[ERROR] welcome photo send failed: %s: %s",
                type(exc).__name__,
                str(exc),
                exc_info=True,
            )
    if not sent_photo:
        await _reply(update.message, _WELCOME_MESSAGE, markup)

    user = update.effective_user
    log.info(
        "[GAME] welcome sent (photo=%s) user=%s",
        sent_photo,
        getattr(user, "id", "?"),
    )


# ---------------------------------------------------------------------------
# /room — group room card
# ---------------------------------------------------------------------------


async def cmd_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    chat = update.effective_chat
    if chat.type not in _GROUP_CHAT_TYPES:
        await _reply(update.message, _PRIVATE_ROOM_MESSAGE)
        return

    if not config.PEN_FIGHT_WEBAPP_URL:
        log.error("[ERROR] PEN_FIGHT_WEBAPP_URL is missing")
        await update.message.reply_text(_WEBAPP_NOT_CONFIGURED)
        return

    markup = _pen_fight_markup("🎮 JOIN PEN FIGHT")
    if markup is None:
        await update.message.reply_text(_WEBAPP_NOT_CONFIGURED)
        return

    await _reply(update.message, _GROUP_CARD_MESSAGE, markup)
    log.info("[GAME] room card posted chat=%s", chat.id)


# ---------------------------------------------------------------------------
# Global error handler — surface the REAL Telegram API message
# ---------------------------------------------------------------------------


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    The previous version logged only type(exc).__name__, which reduced every
    400 Bad Request to a useless "BadRequest" line. Log the full exception
    message (and traceback) so the actual reason is visible — e.g.
    BUTTON_WEBAPP_INFO_INVALID / can't parse entities / message is too long /
    have no rights to send a message.
    """
    err = getattr(context, "error", None)
    if err is None:
        log.error("[ERROR] handler error with no exception (update=%s)", bool(update))
        return
    if isinstance(err, BadRequest):
        log.error("[ERROR] Telegram BadRequest: %s", str(err), exc_info=True)
    elif isinstance(err, TelegramError):
        log.error(
            "[ERROR] Telegram error (%s): %s", type(err).__name__, str(err), exc_info=True
        )
    else:
        log.error(
            "[ERROR] handler error (%s): %s", type(err).__name__, str(err), exc_info=True
        )


# ---------------------------------------------------------------------------
# Application factory — exactly one handler per command
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
