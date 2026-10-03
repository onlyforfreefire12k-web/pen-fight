"""Pyrogram MTProto userbot for Pen Fight Bot.

Runs in its OWN thread with its own event loop (PTB bot has its own).
The PTB bot talks to this module via `call_userbot(coro)`, which uses
`asyncio.run_coroutine_threadsafe`.

Features
  • Login flow (phone → OTP → optional 2FA) — session stored as a STRING
    in SQLite (no .session files, survives ephemeral hosts like Render).
  • Mass-removal (ban/kick) abuse monitor → auto demote + ban
    (decision + punish both live in security.py).
  • VC blacklist enforcer — mutes blacklisted users when they join a voice
    chat (MTProto has no "ban from VC" — mute is the strongest available).
  • Auto-registers every group where the userbot sees activity.
"""

import asyncio
import logging
import threading

from pyrogram import Client, filters, raw
from pyrogram.errors import (
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)

import config
from config import API_HASH, API_ID, OWNER_ID
from database import db
from security import abuse_tracker, punish_admin, should_punish

logger = logging.getLogger(__name__)


class Userbot:
    """Pyrogram MTProto userbot — one instance for the whole process."""

    def __init__(self) -> None:
        self.client: Client | None = None
        self.is_running: bool = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self._login_needs_password: bool = False
        self._ready = threading.Event()

    # ----------------------------------------------------------------- threading

    def start_thread(self) -> threading.Thread:
        """Start the userbot in a background daemon thread."""
        t = threading.Thread(
            target=self._thread_main, name="pen-fight-userbot", daemon=True
        )
        t.start()
        self._ready.wait(timeout=10)  # wait until the loop exists
        return t

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self._ready.set()
        try:
            loop.run_until_complete(self._main())
        except Exception as exc:  # noqa: BLE001
            logger.error("Userbot crashed: %s", exc, exc_info=True)
        finally:
            loop.close()

    async def _main(self) -> None:
        # Ensure the security DB is initialised on this thread too.
        await db.connect()

        # Restore the owner's session from DB, if any.
        if OWNER_ID:
            sess = await db.get_session(OWNER_ID)
            if sess and sess.get("session_string"):
                try:
                    await self._connect(sess["session_string"])
                    logger.info("Userbot session restored from DB.")
                except Exception as exc:
                    logger.warning("Failed to restore session: %s", exc)
                    self.client = None
                    self.is_running = False
            else:
                logger.info("No userbot session yet. Use /login to start.")

        # Keep this loop alive forever.
        while True:
            await asyncio.sleep(3600)

    # ------------------------------------------------------------------ client

    async def _connect(self, session_string: str) -> None:
        """Restore a session and start monitoring on a fresh client."""
        if self.client and self.client.is_connected:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

        client = Client(
            name="pen_fight_userbot",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
        )
        await client.connect()
        self._register_handlers(client)

        me = await client.get_me()
        self.client = client
        self.is_running = True
        logger.info("Userbot connected as %s (%s)", me.first_name, me.id)

    # --------------------------------------------------------------- login flow

    async def login_start(self, phone: str) -> dict:
        """Step 1 — send the verification code."""
        if not API_ID or not API_HASH:
            return {"success": False, "message": "API_ID / API_HASH missing in .env."}
        try:
            # Fresh unauthenticated in-memory client for the login flow.
            if not self.client or not self.client.is_connected:
                self.client = Client(
                    name="pen_fight_login",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    in_memory=True,
                )
                await self.client.connect()

            code = await self.client.send_code(phone)
            self._login_needs_password = False
            return {
                "success": True,
                "message": "Verification code sent.",
                "phone_code_hash": code.phone_code_hash,
            }
        except PhoneNumberInvalid:
            return {"success": False, "message": "Invalid phone number format."}
        except FloodWait as e:
            return {"success": False, "message": f"Flood wait: try again in {e.value}s."}
        except Exception as exc:
            logger.exception("login_start")
            return {"success": False, "message": f"Error: {exc}"}

    async def login_complete(
        self,
        phone: str,
        phone_code_hash: str,
        code: str,
        password: str | None = None,
    ) -> dict:
        """Step 2/3 — verify the code and handle 2FA if needed."""
        if not self.client or not self.client.is_connected:
            return {"success": False, "message": "Login session expired. /login again."}

        try:
            # --- 2FA path ---
            if self._login_needs_password:
                if not password:
                    return {
                        "success": False,
                        "needs_password": True,
                        "message": "Password required.",
                    }
                await self.client.check_password(password)
                self._login_needs_password = False

            # --- code path ---
            else:
                try:
                    await self.client.sign_in(phone, phone_code_hash, code)
                except SessionPasswordNeeded:
                    self._login_needs_password = True
                    return {
                        "success": False,
                        "needs_password": True,
                        "message": "2FA is enabled. Send your password.",
                    }

            # --- success: export & store session string ---
            me = await self.client.get_me()
            sess_string = await self.client.export_session_string()

            await db.save_session(me.id, sess_string, phone)
            await db.touch_session(me.id)
            await db.log(
                "USERBOT_LOGIN", actor_id=me.id, details=f"phone={phone}"
            )

            # Register handlers on the SAME (now-authorised) client.
            self._register_handlers(self.client)
            self.is_running = True

            return {"success": True, "message": "Login successful!", "user_id": me.id}

        except PhoneCodeInvalid:
            return {"success": False, "message": "Invalid code."}
        except PhoneCodeExpired:
            return {"success": False, "message": "Code expired. /login again."}
        except FloodWait as e:
            return {"success": False, "message": f"Flood wait: {e.value}s."}
        except Exception as exc:
            logger.exception("login_complete")
            return {"success": False, "message": f"Error: {exc}"}

    async def logout(self, user_id: int) -> dict:
        """Revoke the session and wipe the DB row."""
        if self.client and self.client.is_connected:
            try:
                await self.client.log_out()
            except Exception as exc:
                logger.warning("log_out error: %s", exc)
            try:
                await self.client.disconnect()
            except Exception:
                pass

        self.client = None
        self.is_running = False
        await db.deactivate_session(user_id)
        await db.log("USERBOT_LOGOUT", actor_id=user_id)
        return {"success": True, "message": "✅ Logged out. Session revoked."}

    # ---------------------------------------------------------------- handlers

    def _register_handlers(self, client: Client) -> None:
        """Attach raw/message handlers. Safe to call twice."""
        if getattr(client, "_penfight_handlers", False):
            return
        client._penfight_handlers = True

        # ---- Abuse monitor (mass ban/kick) — supergroups only ----
        @client.on_raw_update(group=5)
        async def _abuse_monitor(cl, update, users, chats):
            if isinstance(update, raw.types.UpdateChannelParticipant):
                await self._handle_participant_update(cl, update)

        # ---- VC blacklist enforcer ----
        @client.on_raw_update(group=7)
        async def _vc_enforcer(cl, update, users, chats):
            if isinstance(update, raw.types.UpdateGroupCallParticipants):
                await self._handle_vc_update(cl, update)

        # ---- Auto-register any group where the userbot sees activity ----
        @client.on_message(filters.group & ~filters.service, group=10)
        async def _track_group(cl, message):
            if message.chat and message.chat.id:
                await db.add_group(message.chat.id, message.chat.title or "")

        logger.info("Userbot handlers registered.")

    async def _handle_participant_update(self, client: Client, update) -> None:
        """Handle one UpdateChannelParticipant — abuse detection entry point."""
        try:
            actor_id = update.actor_id
            if not actor_id:
                return

            me = await client.get_me()
            if actor_id == me.id:
                return  # our own action

            # Only care about bans / kicks / removals.
            new_p = update.new_participant
            was_removal = new_p is None or isinstance(
                new_p, raw.types.ChannelParticipantBanned
            )
            if not was_removal:
                return

            chat_id = int(f"-100{update.channel_id}")

            # security.py decides (skips owner, auth users, trusted admins).
            changed, count = await should_punish(actor_id, chat_id)

            logger.info(
                "Removal by %s in %s — %d/%d in window",
                actor_id, chat_id, count, config.ABUSE_THRESHOLD,
            )

            if not changed:
                return

            result = await punish_admin(client, chat_id, actor_id, count)

            if result.get("ok"):
                await self._notify_owner(
                    "🚨 ADMIN ABUSE BLOCKED\n\n"
                    f"Chat: {chat_id}\n"
                    f"Admin: {actor_id}\n"
                    f"Removals in {config.ABUSE_WINDOW_SECONDS}s: {count}\n"
                    "Action: DEMOTED + BANNED"
                )
            elif "error" in result:
                await self._notify_owner(
                    f"⚠️ Could not punish {actor_id} in {chat_id}: "
                    f"{result.get('error')}"
                )
            # else: skipped (protected / trusted) → no alert needed.

            abuse_tracker.reset(actor_id, chat_id)

        except Exception as exc:
            logger.exception("_handle_participant_update: %s", exc)

    async def _handle_vc_update(self, client: Client, update) -> None:
        """Mute blacklisted users in any voice chat they try to join."""
        try:
            call = update.call
            for participant in update.participants:
                peer = participant.peer
                if not isinstance(peer, raw.types.PeerUser):
                    continue
                uid = peer.user_id

                if not await db.is_blacklisted(uid):
                    continue

                try:
                    input_peer = await client.resolve_peer(uid)
                    # MTProto exposes no "ban from VC" — mute is the strongest
                    # action available for a non-participant admin.
                    await client.invoke(
                        raw.functions.phone.EditGroupCallParticipant(
                            call=call,
                            participant=input_peer,
                            muted=True,
                        )
                    )
                    logger.info("🔇 Muted blacklisted %s in VC %s", uid, call.id)
                    await db.log(
                        "VC_MUTE",
                        severity="WARNING",
                        target_id=uid,
                        details=f"call_id={call.id}",
                    )
                except Exception as exc:
                    logger.warning("VC action failed for %s: %s", uid, exc)

        except Exception as exc:
            logger.exception("_handle_vc_update: %s", exc)

    # ---------------------------------------------------------------------- misc

    async def _notify_owner(self, text: str) -> None:
        """DM the owner through the userbot (works without the PTB bot)."""
        if not OWNER_ID or not self.client or not self.client.is_connected:
            return
        try:
            await self.client.send_message(OWNER_ID, text)
        except Exception as exc:
            logger.warning("Owner notification failed: %s", exc)


# Global instance — import this from bot.py / live.py
userbot = Userbot()


# ---------------------------------------------------------------------------
# Cross-thread bridge — call a userbot coroutine from the PTB thread
# ---------------------------------------------------------------------------

async def call_userbot(coro):
    """
    Run a coroutine on the userbot's event loop and await its result from
    the current (PTB) event loop.
    """
    if userbot.loop is None:
        return {"success": False, "message": "Userbot thread not started."}
    fut = asyncio.run_coroutine_threadsafe(coro, userbot.loop)
    return await asyncio.wrap_future(fut, loop=asyncio.get_running_loop())


def start_userbot_thread() -> threading.Thread:
    """Called from live.py to spin up the userbot thread."""
    return userbot.start_thread()
