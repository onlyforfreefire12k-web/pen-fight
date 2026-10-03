"""Security engine — abuse detection + punish (demote + ban).

Abuse detection
  Every time a user is banned/kicked in a monitored supergroup, Pyrogram
  sends a raw `UpdateChannelParticipant` with `actor_id`. We keep a sliding
  window per (actor, chat). If the count crosses ABUSE_THRESHOLD within
  ABUSE_WINDOW_SECONDS, we auto-demote + auto-ban the actor.

Trusted admins
  Actors in `trusted_admins` are exempt — /trust command adds them.
"""

import logging
import time
from collections import defaultdict, deque

from pyrogram import Client
from pyrogram.types import ChatPrivileges

import config
from config import ABUSE_THRESHOLD, ABUSE_WINDOW_SECONDS, OWNER_ID
from database import db

logger = logging.getLogger(__name__)


class AbuseTracker:
    """Sliding-window counter per (actor_id, chat_id)."""

    def __init__(self, window: int = ABUSE_WINDOW_SECONDS):
        self.window = window
        self._hits: dict[tuple[int, int], deque[float]] = defaultdict(deque)

    def record(self, actor_id: int, chat_id: int) -> int:
        """Record a removal. Returns how many in the current window."""
        now = time.time()
        dq = self._hits[(actor_id, chat_id)]
        dq.append(now)
        while dq and now - dq[0] > self.window:
            dq.popleft()
        return len(dq)

    def reset(self, actor_id: int, chat_id: int) -> None:
        self._hits.pop((actor_id, chat_id), None)


# Global tracker
abuse_tracker = AbuseTracker()


def _chat_id_from_raw(raw_channel_id: int) -> int:
    """Convert raw Pyrogram channel_id to a proper PTB-style chat_id."""
    return int(f"-100{raw_channel_id}")


async def punish_admin(client, chat_id: int, admin_id: int, removals: int) -> dict:
    """Demote + ban an abusive admin. Returns a result dict."""
    # Never touch owner or trusted admins
    if admin_id == OWNER_ID:
        return {"ok": False, "reason": "target is owner"}
    if await db.is_trusted(admin_id):
        logger.info("Skipping punish for trusted admin %s", admin_id)
        return {"ok": False, "reason": "trusted"}

    try:
        # 1. DEMOTE — strip all admin privileges (back to member)
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
        # 2. BAN
        await client.ban_chat_member(chat_id, admin_id)

        await db.log(
            "ABUSE_PUNISHED", severity="CRITICAL",
            actor_id=admin_id, chat_id=chat_id,
            details=f"{removals} removals in {ABUSE_WINDOW_SECONDS}s — demoted + banned",
        )
        logger.warning(
            "🚨 Abusive admin %s punished in %s (%d removals)",
            admin_id, chat_id, removals,
        )
        return {"ok": True, "action": "demoted+banned"}

    except Exception as exc:
        # Usually means: target is creator, or outranks owner's userbot.
        logger.warning("Could not punish %s in %s: %s", admin_id, chat_id, exc)
        await db.log(
            "ABUSE_PUNISH_FAILED", severity="ERROR",
            actor_id=admin_id, chat_id=chat_id, details=str(exc),
        )
        return {"ok": False, "action": "failed", "error": str(exc)}


async def should_punish(actor_id: int, chat_id: int) -> bool:
    """Decide if an actor crossed the abuse threshold."""
    if await db.is_trusted(actor_id):
        return False
    count = abuse_tracker.record(actor_id, chat_id)
    return count >= ABUSE_THRESHOLD
