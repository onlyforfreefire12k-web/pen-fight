"""
config.py
---------
Central configuration for the Pen Fight backend.

The simplifed bot only needs the Telegram bot token; Render injects PORT.
No secrets are ever hard-coded and no secret value is ever logged.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("backend.config")


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing/invalid."""


REQUIRED_ENV_VARS = (
    "TELEGRAM_BOT_TOKEN",
    "PEN_FIGHT_WEBAPP_URL",
)

DEFAULT_PORT = 10000


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")

# The Pen Fight Web App URL. NEVER hard-coded in the bot code — it comes from
# the environment (Render dashboard / .env) so the same deploy can point at a
# different frontend without a code change.
PEN_FIGHT_WEBAPP_URL = os.getenv("PEN_FIGHT_WEBAPP_URL", "").strip()

# Render injects PORT automatically; default safely to 10000 when unset or
# malformed (e.g. local runs without the variable).
try:
    PORT = int(os.environ.get("PORT") or str(DEFAULT_PORT))
except (TypeError, ValueError):
    PORT = DEFAULT_PORT

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def missing_env_vars() -> list[str]:
    """Return the list of required environment variables that are not set."""
    return [name for name in REQUIRED_ENV_VARS if globals().get(name) in (None, "")]


def validate_or_raise() -> None:
    """Fail fast at startup if anything required is missing."""
    missing = missing_env_vars()
    if missing:
        raise ConfigError(
            "Missing required environment variables: "
            + ", ".join(sorted(missing))
        )
    if not PEN_FIGHT_WEBAPP_URL.startswith("https://"):
        raise ConfigError(
            "PEN_FIGHT_WEBAPP_URL must be a full https:// URL "
            "(Telegram Web App buttons require HTTPS), got an invalid value."
        )
    log.info(
        "[LIVE] Config ok — port=%s webapp_url=%s", PORT, PEN_FIGHT_WEBAPP_URL
    )
