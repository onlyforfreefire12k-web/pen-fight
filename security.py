"""Security engine — abuse detection + punish (demote / demote+ban).

Punish modes
  • "ban"    → DEMOTE + BAN  (for /banall, /kickall commands — destructive)
  • "demote" → DEMOTE only   (for drip bans — one-by-one, less harmful)

Never punished
  • OWNER_ID
  • Anyone in AUTH_USER_IDS
  • Anyone in `trusted_admins` (added via /trust)
"""

import logging
import time
from collections import defaultdict, deque

from pyrogram import Client
from pyrogram.types import ChatPrivileges

from config import (
    ABUSE_THRESHOLD,
    ABUSE_WINDOW_SECONDS,
    AUTH_USER_IDS,
    OWNER_ID,
)
from database import db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------

class AbuseTracker:
    def __init__(self, window: int = ABUSE_WINDOW_SECONDS):
        self.window = window
        self._hits: dict[tuple[int, int], deque[float]] = defaultdict(deque)

    def record(self, actor_id: int, chat_id: int) -> int:
        now = time.time()
        dq = self._hits[(actor_id, chat_id)]
        dq.append(now)
        while dq and now - dq[0] > self.window:
            dq.popleft()
        return len(dq)

    def reset(self, actor_id: int, chat_id: int) -> None:
        self._hits.pop((actor_id, chat_id), None)


abuse_tracker = AbuseTracker()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_protected(actor_id: int) -> bool:
    return actor_id == OWNER_ID or actor_id in AUTH_USER_IDS


_NOTHING_PRIVS = ChatPrivileges(
    can_manage_chat=False,
    can_delete_messages=False,
    can_restrict_members=False,
    can_promote_members=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_video_chats=False,
    can_post_messages=False,
    can_edit_messages=False,
    can_manage_topics=False,
)


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

async def should_punish(actor_id: int, chat_id: int) -> tuple[bool, int]:
    """Record one removal; return (crossed_threshold, count_in_window)."""
    if _is_protected(actor_id):
        return False, 0
    if await db.is_trusted(actor_id):
        return False, 0
    count = abuse_tracker.record(actor_id, chat_id)
    return count >= ABUSE_THRESHOLD, count


# ---------------------------------------------------------------------------
# Punish
# ---------------------------------------------------------------------------

async def punish_admin(
    client: Client,
    chat_id: int,
    admin_id: int,
    removals: int,
    mode: str = "ban",
) -> dict:
    """
    DEMOTE (always) and optionally BAN an abusive admin.

    Args:
        mode = "ban"     → DEMOTE + BAN  (mass commands)
        mode = "demote"  → DEMOTE only   (drip bans)
    """
    # Safety net
    if _is_protected(admin_id):
        return {"ok": False, "reason": "protected"}
    if await db.is_trusted(admin_id):
        return {"ok": False, "reason": "trusted"}

    try:
        # 1) DEMOTE — strip every admin privilege
        await client.promote_chat_member(
            chat_id, admin_id, privileges=_NOTHING_PRIVS,
        )

        # 2) optionally BAN
        if mode == "ban":
            await client.ban_chat_member(chat_id, admin_id)
            await db.log(
                "ABUSE_PUNISHED",
                severity="CRITICAL",
                actor_id=admin_id,
                chat_id=chat_id,
                details=f"{removals} removals — DEMOTED + BANNED",
            )
            logger.warning(
                "🚨 Admin %s DEMOTED + BANNED in %s (%d removals)",
                admin_id, chat_id, removals,
            )
            return {"ok": True, "action": "demoted+banned"}

        # demote-only
        await db.log(
            "ABUSE_DEMOTED",
            severity="WARNING",
            actor_id=admin_id,
            chat_id=chat_id,
            details=f"{removals} removals — DEMOTED (drip ban)",
        )
        logger.warning(
            "⚠️ Admin %s DEMOTED in %s (%d drip removals)",
            admin_id, chat_id, removals,
        )
        return {"ok": True, "action": "demoted"}

    except Exception as exc:
        logger.warning("Could not punish %s in %s: %s", admin_id, chat_id, exc)
        await db.log(
            "ABUSE_PUNISH_FAILED",
            severity="ERROR",
            actor_id=admin_id,
            chat_id=chat_id,
            details=str(exc),
        )
        return {"ok": False, "action": "failed", "error": str(exc)}
