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
)

DEFAULT_PORT = 10000


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")

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
    log.info("[LIVE] Config ok — port=%s", PORT)
