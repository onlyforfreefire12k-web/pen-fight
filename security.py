"""Security engine — abuse detection + punish (demote + ban).

How abuse detection works
  1. Every time a user is banned/kicked in a supergroup where the userbot
     is admin, Pyrogram sends `raw.types.UpdateChannelParticipant` with
     `actor_id` = the admin who did it.
  2. `abuse_tracker.record(actor_id, chat_id)` keeps a sliding window of
      removal timestamps per (actor, chat).
  3. If the count crosses `ABUSE_THRESHOLD` within `ABUSE_WINDOW_SECONDS`,
     `punish_admin()` DEMOTES then BANS the actor.

Never auto-punished
  • OWNER_ID
  • Anyone in AUTH_USER_IDS (bot's authorized users)
  • Anyone in the `trusted_admins` table (added via /trust)
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
# Sliding-window abuse tracker
# ---------------------------------------------------------------------------

class AbuseTracker:
    """Per (actor_id, chat_id) sliding window of removal timestamps."""

    def __init__(self, window: int = ABUSE_WINDOW_SECONDS):
        self.window = window
        self._hits: dict[tuple[int, int], deque[float]] = defaultdict(deque)

    def record(self, actor_id: int, chat_id: int) -> int:
        """Record one removal and return the count within the window."""
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
    """Never auto-punish the owner or any authorized user."""
    return actor_id == OWNER_ID or actor_id in AUTH_USER_IDS


def _chat_id_from_raw(raw_channel_id: int) -> int:
    """RAW Pyrogram channel_id  →  PTB-style supergroup chat_id  (-100…)."""
    return int(f"-100{raw_channel_id}")


# ---------------------------------------------------------------------------
# Decision + punish
# ---------------------------------------------------------------------------

async def should_punish(actor_id: int, chat_id: int) -> tuple[bool, int]:
    """
    Record one removal and decide if the actor crossed the threshold.

    Returns:
        (crossed_threshold: bool, count_in_window: int)

    Protected actors (owner / auth users / trusted) are NOT recorded —
    returns (False, 0).
    """
    if _is_protected(actor_id):
        return False, 0
    if await db.is_trusted(actor_id):
        return False, 0

    count = abuse_tracker.record(actor_id, chat_id)
    return count >= ABUSE_THRESHOLD, count


async def punish_admin(
    client: Client, chat_id: int, admin_id: int, removals: int
) -> dict:
    """
    DEMOTE then BAN an abusive admin (defence in depth).

    Returns:
        {'ok': True,  'action': 'demoted+banned'}
        {'ok': False, 'reason': 'protected'|'trusted'}         — skipped
        {'ok': False, 'action': 'failed', 'error': '...'}      — Telegram refused
    """
    # Safety net — never punish protected actors even if called directly.
    if _is_protected(admin_id):
        return {"ok": False, "reason": "protected"}
    if await db.is_trusted(admin_id):
        return {"ok": False, "reason": "trusted"}

    try:
        # 1) DEMOTE — strip every admin privilege (back to plain member)
        await client.promote_chat_member(
            chat_id,
            admin_id,
            privileges=ChatPrivileges(
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
            ),
        )

        # 2) BAN — permanent
        await client.ban_chat_member(chat_id, admin_id)

        await db.log(
            "ABUSE_PUNISHED",
            severity="CRITICAL",
            actor_id=admin_id,
            chat_id=chat_id,
            details=(
                f"{removals} removals in {ABUSE_WINDOW_SECONDS}s "
                f"— demoted + banned"
            ),
        )
        logger.warning(
            "🚨 Abusive admin %s punished in %s (%d removals)",
            admin_id, chat_id, removals,
        )
        return {"ok": True, "action": "demoted+banned"}

    except Exception as exc:
        # Usually: target is the creator, or outranks the userbot.
        logger.warning("Could not punish %s in %s: %s", admin_id, chat_id, exc)
        await db.log(
            "ABUSE_PUNISH_FAILED",
            severity="ERROR",
            actor_id=admin_id,
            chat_id=chat_id,
            details=str(exc),
        )
        return {"ok": False, "action": "failed", "error": str(exc)}
