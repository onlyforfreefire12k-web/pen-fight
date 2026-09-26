# Pen Fight — Telegram Bot Backend

A deliberately **minimal** backend for the Pen Fight 3D game. It does one thing:
post Telegram **Web App** buttons so the game at
`https://node-static-3fe2b.wasmer.app/` opens **inside Telegram**.

```
Telegram
   ├── /start  (private)   → 🎮 PEN FIGHT welcome + [🎮 OPEN PEN FIGHT]
   └── /room   (groups)    → 🎮 PEN FIGHT ROOM  + [🎮 JOIN PEN FIGHT]

Both buttons are InlineKeyboardButton(web_app=WebAppInfo(WEB_APP_URL)).
There are NO launch codes, NO tokens, NO startapp payloads, NO generated
URLs, NO membership checks — taping one of them simply opens the fixed Web
App URL in Telegram's WebView/Mini App interface.
```

## Files

| File | Responsibility |
|---|---|
| `live.py` | Entry point: Flask health server (`0.0.0.0:$PORT`) + Telegram long-polling, exactly as before |
| `bot.py` | `/start` (private welcome card) and `/room` (group room card), both with a `web_app` button |
| `config.py` | The single required env var (`TELEGRAM_BOT_TOKEN`) + `PORT` |
| `requirements.txt` | `Flask` + `python-telegram-bot` only |
| `render.yaml` | Render blueprint |

## Commands

| Where | Command | Behaviour |
|---|---|---|
| private | `/start` | 🎮 PEN FIGHT welcome card (artwork if bundled, otherwise text) + `🎮 OPEN PEN FIGHT` Web App button |
| group | `/room` | 🎮 PEN FIGHT ROOM card + `🎮 JOIN PEN FIGHT` Web App button |
| private | `/room` | Replies `Use /room inside your Telegram group to open the Pen Fight room.` |

The buttons always open `https://node-static-3fe2b.wasmer.app/` **inside
Telegram** (via `web_app=WebAppInfo(...)`), never in an external browser.

## Environment

| Variable | Required | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | From @BotFather |
| `PORT` | auto | Render injects it; defaults to `10000` |
| `LOG_LEVEL` | optional | Default `INFO` |

The game URL itself is hard-coded in `bot.py` (per product spec) — it is not
a secret.

## Render

- **Web Service**, runtime **Python 3** (root dir `backend` if needed)
- **Build:** `pip install -r requirements.txt`
- **Start:** `python live.py`
- **Health check path:** `/health`

## Telegram setup

1. `@BotFather` → `/newbot` → copy the token into `TELEGRAM_BOT_TOKEN`.
2. Optional (prettier "Open" experience): `/setwebapp` (or `/myapps` → set the
   Web App URL) to the same `https://node-static-3fe2b.wasmer.app/`. `web_app`
   buttons work even without this.
3. Add the bot to your group. In the group it answers `/room`; in private it
   answers `/start`.

## Local testing

```bash
cd backend
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...   # real token
python live.py
# curl http://localhost:10000/        -> 3D Room Backend Online
# curl http://localhost:10000/health  -> {"status":"ok","service":"3d-room-backend"}
# DM the bot /start, and send /room in a group.
```
