import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

import config


log = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎮 PLAY GAME",
                web_app=WebAppInfo(url=config.GAME_WEBAPP_URL)
            )
        ]
    ])

    await update.message.reply_text(
        "🎮 PEN FIGHT\n\n"
        "Welcome to Pen Fight!\n\n"
        "Tap the button below to enter the game.",
        reply_markup=keyboard
    )


async def game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎮 PLAY GAME",
                web_app=WebAppInfo(url=config.GAME_WEBAPP_URL)
            )
        ]
    ])

    await update.message.reply_text(
        "🎮 PEN FIGHT\n\n"
        "Ready to play?\n\n"
        "Tap the button below to enter the game.",
        reply_markup=keyboard
    )


def create_bot():
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    if not config.GAME_WEBAPP_URL:
        raise RuntimeError("GAME_WEBAPP_URL is missing")

    if not config.GAME_WEBAPP_URL.startswith("https://"):
        raise RuntimeError("GAME_WEBAPP_URL must use HTTPS")

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("game", game))

    return application
