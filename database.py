"""SQLite storage for the Pen Fight security layer.

Tables:
    sessions          — userbot session_string per owner (no .session files!)
    blacklist         — users auto-kicked from groups AND voice chats
    trusted_admins    — admins exempt from abuse auto-punish
    monitored_groups  — groups where the userbot watches activity
    security_logs     — audit trail
"""

import logging
from datetime import datetime, timezone

import aiosqlite

from config import SESSION_DB

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    user_id         INTEGER PRIMARY KEY,
    phone           TEXT,
    session_string  TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    last_used       TEXT
);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id     INTEGER PRIMARY KEY,
    added_by    INTEGER,
    reason      TEXT,
    added_at    TEXT
);

CREATE TABLE IF NOT EXISTS trusted_admins (
    user_id     INTEGER PRIMARY KEY,
    added_by    INTEGER,
    added_at    TEXT
);

CREATE TABLE IF NOT EXISTS monitored_groups (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT,
    added_at    TEXT
);

CREATE TABLE IF NOT EXISTS security_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT,
    severity    TEXT,
    actor_id    INTEGER,
    target_id   INTEGER,
    chat_id     INTEGER,
    details     TEXT,
    timestamp   TEXT
);
"""


class Database:
    def __init__(self, path: str = SESSION_DB):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("Database ready: %s", self.path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------ sessions
    async def save_session(self, user_id: int, session_string: str, phone: str | None = None) -> None:
        await self._db.execute(
            """INSERT INTO sessions (user_id, phone, session_string, is_active, last_used)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 phone=excluded.phone,
                 session_string=excluded.session_string,
                 is_active=1,
                 last_used=excluded.last_used""",
            (user_id, phone, session_string, _now()),
        )
        await self._db.commit()

    async def get_session(self, user_id: int) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM sessions WHERE user_id=? AND is_active=1", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def deactivate_session(self, user_id: int) -> None:
        await self._db.execute(
            "UPDATE sessions SET is_active=0, session_string='' WHERE user_id=?",
            (user_id,),
        )
        await self._db.commit()

    async def touch_session(self, user_id: int) -> None:
        await self._db.execute(
            "UPDATE sessions SET last_used=? WHERE user_id=?", (_now(), user_id)
        )
        await self._db.commit()

    # ----------------------------------------------------------------- blacklist
    async def add_blacklist(self, user_id: int, added_by: int, reason: str | None = None) -> None:
        await self._db.execute(
            """INSERT INTO blacklist (user_id, added_by, reason, added_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 added_by=excluded.added_by, reason=excluded.reason""",
            (user_id, added_by, reason, _now()),
        )
        await self._db.commit()

    async def remove_blacklist(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM blacklist WHERE user_id=?", (user_id,))
        await self._db.commit()

    async def is_blacklisted(self, user_id: int) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM blacklist WHERE user_id=?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def list_blacklist(self, limit: int = 20) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM blacklist ORDER BY added_at DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------- trusted
    async def add_trusted(self, user_id: int, added_by: int) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO trusted_admins (user_id, added_by, added_at) VALUES (?, ?, ?)",
            (user_id, added_by, _now()),
        )
        await self._db.commit()

    async def remove_trusted(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM trusted_admins WHERE user_id=?", (user_id,))
        await self._db.commit()

    async def is_trusted(self, user_id: int) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM trusted_admins WHERE user_id=?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None

    # ---------------------------------------------------------- monitored groups
    async def add_group(self, chat_id: int, title: str | None = None) -> None:
        await self._db.execute(
            """INSERT INTO monitored_groups (chat_id, title, added_at)
               VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title""",
            (chat_id, title, _now()),
        )
        await self._db.commit()

    async def remove_group(self, chat_id: int) -> None:
        await self._db.execute("DELETE FROM monitored_groups WHERE chat_id=?", (chat_id,))
        await self._db.commit()

    async def list_groups(self) -> list[dict]:
        async with self._db.execute("SELECT * FROM monitored_groups") as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ---------------------------------------------------------------------- logs
    async def log(
        self, event_type: str, severity: str = "INFO",
        actor_id: int | None = None, target_id: int | None = None,
        chat_id: int | None = None, details: str | None = None,
    ) -> None:
        await self._db.execute(
            """INSERT INTO security_logs
               (event_type, severity, actor_id, target_id, chat_id, details, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_type, severity, actor_id, target_id, chat_id, details, _now()),
        )
        await self._db.commit()

    async def recent_logs(self, limit: int = 10) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM security_logs ORDER BY id DESC LIMIT ?", (limit,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# Global instance — import this everywhere
db = Database()
