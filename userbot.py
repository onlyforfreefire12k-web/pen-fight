"""Pyrogram MTProto userbot for Pen Fight Bot.

Runs in its OWN thread with its own event loop (PTB bot has its own).
PTB talks to this via `call_userbot(coro)` (run_coroutine_threadsafe).

Defence layers
  1. MASS-COMMAND WATCHER  — /banall /kickall /muteall /unbanall /
                             /massban /killall /nuke → instant DEMOTE + BAN
                             If actor is a bot → also punish its sponsor.
  2. DRIP-BAN DETECTOR     — UpdateChannelParticipant sliding window →
                             DEMOTE only after ABUSE_THRESHOLD removals.
  3. SPONSOR TRACKER       — remembers who promoted each admin, so bot
                             misbehaviour also punishes the human behind it.
  4. VC BLACKLIST          — mutes blacklisted users when they join a VC.
  5. GROUP AUTO-REGISTER   — records every group the userbot acts in.
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
from config import API_HASH, API_ID, AUTH_USER_IDS, OWNER_ID
from database import db
from security import abuse_tracker, punish_admin, should_punish

logger = logging.getLogger(__name__)


# Commands that any abuse-aware group must catch instantly.
MASS_COMMANDS = [
    "banall", "kickall", "muteall", "unbanall", "unmuteall",
    "massban", "killall", "nuke", "wipeout", "allban",
]


class Userbot:
    """Pyrogram MTProto userbot — one instance for the whole process."""

    def __init__(self) -> None:
        self.client: Client | None = None
        self.is_running: bool = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self._login_needs_password: bool = False
        self._ready = threading.Event()

        # {admin_user_id: who_promoted_them}
        self._admin_sponsor: dict[int, int] = {}

    # ----------------------------------------------------------------- threading

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(
            target=self._thread_main, name="pen-fight-userbot", daemon=True
        )
        t.start()
        self._ready.wait(timeout=10)
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
        await db.connect()
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
                logger.info("No userbot session yet. Use /login.")

        while True:
            await asyncio.sleep(3600)

    # ------------------------------------------------------------------ client

    async def _connect(self, session_string: str) -> None:
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
        if not API_ID or not API_HASH:
            return {"success": False, "message": "API_ID / API_HASH missing."}
        try:
            if not self.client or not self.client.is_connected:
                self.client = Client(
                    name="pen_fight_login",
                    api_id=API_ID, api_hash=API_HASH, in_memory=True,
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
            return {"success": False, "message": "Invalid phone format."}
        except FloodWait as e:
            return {"success": False, "message": f"Flood wait: {e.value}s."}
        except Exception as exc:
            logger.exception("login_start")
            return {"success": False, "message": f"Error: {exc}"}

    async def login_complete(
        self, phone: str, phone_code_hash: str,
        code: str, password: str | None = None,
    ) -> dict:
        if not self.client or not self.client.is_connected:
            return {"success": False, "message": "Login session expired. /login again."}
        try:
            if self._login_needs_password:
                if not password:
                    return {"success": False, "needs_password": True,
                            "message": "Password required."}
                await self.client.check_password(password)
                self._login_needs_password = False
            else:
                try:
                    await self.client.sign_in(phone, phone_code_hash, code)
                except SessionPasswordNeeded:
                    self._login_needs_password = True
                    return {"success": False, "needs_password": True,
                            "message": "2FA is enabled. Send your password."}

            me = await self.client.get_me()
            sess_string = await self.client.export_session_string()

            await db.save_session(me.id, sess_string, phone)
            await db.touch_session(me.id)
            await db.log("USERBOT_LOGIN", actor_id=me.id, details=f"phone={phone}")

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
        if getattr(client, "_penfight_handlers", False):
            return
        client._penfight_handlers = True

        # ---- 1. MASS COMMAND WATCHER (runs FIRST) ----
        @client.on_message(
            filters.group & filters.command(MASS_COMMANDS), group=4
        )
        async def _mass_cmd_watcher(cl, message):
            await self._handle_mass_command(cl, message)

        # ---- 2. Participant updates: sponsor + drip bans ----
        @client.on_raw_update(group=5)
        async def _abuse_monitor(cl, update, users, chats):
            if isinstance(update, raw.types.UpdateChannelParticipant):
                await self._handle_participant_update(cl, update, users)

        # ---- 3. VC blacklist ----
        @client.on_raw_update(group=7)
        async def _vc_enforcer(cl, update, users, chats):
            if isinstance(update, raw.types.UpdateGroupCallParticipants):
                await self._handle_vc_update(cl, update)

        # ---- 4. Group auto-register ----
        @client.on_message(filters.group & ~filters.service, group=10)
        async def _track_group(cl, message):
            if message.chat and message.chat.id:
                await db.add_group(message.chat.id, message.chat.title or "")

        logger.info("Userbot handlers registered.")

    # -------------------------------------------------- 1. mass command handler

    async def _handle_mass_command(self, client: Client, message) -> None:
        actor = message.from_user
        if not actor:
            return

        me = await client.get_me()
        if actor.id == me.id:
            return  # our own command
        if actor.id in AUTH_USER_IDS:
            await db.log("MASS_CMD_BY_AUTH", severity="WARNING",
                         actor_id=actor.id, chat_id=message.chat.id,
                         details=message.text)
            return
        if await db.is_trusted(actor.id):
            return

        logger.critical(
            "🚨 MASS COMMAND '%s' by %s in %s",
            message.text, actor.id, message.chat.id,
        )

        # 1) Punish actor immediately (demote + ban)
        await punish_admin(
            client, message.chat.id, actor.id, removals=999, mode="ban",
        )

        # 2) If actor is a bot → also punish its sponsor
        if actor.is_bot:
            sponsor = self._admin_sponsor.get(actor.id)
            if sponsor and sponsor not in AUTH_USER_IDS and sponsor != me.id:
                logger.warning("Punishing sponsor %s of bot %s", sponsor, actor.id)
                await punish_admin(
                    client, message.chat.id, sponsor, removals=999, mode="ban",
                )
                await self._notify_owner(
                    "🚨 SPONSOR OF BANALL BOT PUNISHED\n\n"
                    f"Chat: {message.chat.id}\n"
                    f"Bot: {actor.id}\n"
                    f"Sponsor (human): {sponsor}\n"
                    f"Action: DEMOTED + BANNED"
                )

        await self._notify_owner(
            "🚨 MASS COMMAND BLOCKED\n\n"
            f"Chat: {message.chat.id}\n"
            f"Command: {message.text}\n"
            f"Actor: {actor.id} · is_bot={actor.is_bot}\n"
            "Action: DEMOTED + BANNED"
        )
        abuse_tracker.reset(actor.id, message.chat.id)

    # ------------------------------------------------ 2. participant updates

    async def _handle_participant_update(
        self, client: Client, update, users,
    ) -> None:
        try:
            actor_id = update.actor_id
            if not actor_id:
                return
            me = await client.get_me()
            if actor_id == me.id:
                return

            prev_p = update.prev_participant
            new_p = update.new_participant

            prev_is_admin = isinstance(
                prev_p,
                (raw.types.ChannelParticipantAdmin,
                 raw.types.ChannelParticipantCreator),
            )
            new_is_admin = isinstance(
                new_p,
                (raw.types.ChannelParticipantAdmin,
                 raw.types.ChannelParticipantCreator),
            )

            # ---- promotion → remember the sponsor ----
            if not prev_is_admin and new_is_admin:
                self._admin_sponsor[update.user_id] = actor_id
                logger.info(
                    "Admin %s promoted by %s in -100%s",
                    update.user_id, actor_id, update.channel_id,
                )
                return

            # ---- removal → drip-ban detection ----
            was_removal = new_p is None or isinstance(
                new_p, raw.types.ChannelParticipantBanned
            )
            if not was_removal:
                return

            chat_id = int(f"-100{update.channel_id}")
            changed, count = await should_punish(actor_id, chat_id)
            if not changed:
                return

            # Drip ban → DEMOTE only (no ban)
            result = await punish_admin(
                client, chat_id, actor_id, removals=count, mode="demote",
            )
            if result.get("ok"):
                await self._notify_owner(
                    "⚠️ DRIP-BAN DETECTED\n\n"
                    f"Chat: {chat_id}\n"
                    f"Admin: {actor_id}\n"
                    f"Removals in {config.ABUSE_WINDOW_SECONDS}s: {count}\n"
                    "Action: DEMOTED (not banned)"
                )
            elif "error" in result:
                await self._notify_owner(
                    f"⚠️ Could not demote {actor_id} in {chat_id}: "
                    f"{result.get('error')}"
                )

            abuse_tracker.reset(actor_id, chat_id)

        except Exception as exc:
            logger.exception("_handle_participant_update: %s", exc)

    # ------------------------------------------------------- 3. VC blacklist

    async def _handle_vc_update(self, client: Client, update) -> None:
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
                    await client.invoke(
                        raw.functions.phone.EditGroupCallParticipant(
                            call=call, participant=input_peer, muted=True,
                        )
                    )
                    logger.info("🔇 Muted blacklisted %s in VC %s", uid, call.id)
                    await db.log("VC_MUTE", severity="WARNING",
                                 target_id=uid, details=f"call_id={call.id}")
                except Exception as exc:
                    logger.warning("VC action failed for %s: %s", uid, exc)
        except Exception as exc:
            logger.exception("_handle_vc_update: %s", exc)

    # ---------------------------------------------------------------------- misc

    async def _notify_owner(self, text: str) -> None:
        if not OWNER_ID or not self.client or not self.client.is_connected:
            return
        try:
            await self.client.send_message(OWNER_ID, text)
        except Exception as exc:
            logger.warning("Owner notification failed: %s", exc)


userbot = Userbot()


# ---------------------------------------------------------------------------
# Cross-thread bridge
# ---------------------------------------------------------------------------

async def call_userbot(coro):
    if userbot.loop is None:
        return {"success": False, "message": "Userbot thread not started."}
    fut = asyncio.run_coroutine_threadsafe(coro, userbot.loop)
    return await asyncio.wrap_future(fut, loop=asyncio.get_running_loop())


def start_userbot_thread() -> threading.Thread:
    return userbot.start_thread()
