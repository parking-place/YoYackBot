"""1.4.3 식단 schedule: 21:00 call the role, 22:00 call those who posted nothing, 22:30 judge.

Each server's steps are recorded once per day (`diet_runs`) before they run, so a restart never
repeats a ping. A step that is late (the bot was down) runs only inside its grace window.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import discord

from yoyackbot.channel_config import valid_channel
from yoyackbot.diet import SQLiteDietStore
from yoyackbot.notices import localize

LOGGER = logging.getLogger(__name__)
DEFAULT_ZONE = ZoneInfo("Asia/Seoul")
STEPS = (
    ("call", time(21, 0), timedelta(minutes=50)),
    ("nag", time(22, 0), timedelta(minutes=50)),
    ("judge", time(22, 30), None),  # any time until the day ends
)
HISTORY_LIMIT = 2000
NAG_LIMIT = 60  # mentions in one nag message
CALL = "🐷 {role} 오늘 식단을 올리시오! 🍽️"
NAG = "🐷 {members} 아직 식단이 안 올라왔소! 30분 남았소. ⏰"


@dataclass(frozen=True)
class DietPost:
    """One message in the diet channel that day (no bots, no `!!` commands)."""

    author_id: int
    text: str
    attachments: tuple[object, ...]
    at: datetime


async def day_posts(channel: object, start: datetime, end: datetime) -> list[DietPost]:
    posts = []
    async for message in channel.history(
        after=start, before=end, limit=HISTORY_LIMIT, oldest_first=True,
    ):
        author = getattr(message, "author", None)
        content = (getattr(message, "content", "") or "").strip()
        attachments = tuple(getattr(message, "attachments", ()) or ())
        if author is None or getattr(author, "bot", False) or content.startswith("!!"):
            continue
        if not content and not attachments:
            continue
        posts.append(DietPost(author.id, content, attachments, message.created_at))
    return posts


async def role_members(guild: object, role_id: int) -> list[int]:
    """The role's people (no bots), read from Discord (needs the members intent)."""
    found = []
    async for member in guild.fetch_members(limit=None):
        if getattr(member, "bot", False):
            continue
        if any(getattr(role, "id", None) == role_id for role in getattr(member, "roles", ())):
            found.append(member.id)
    return sorted(found)


Judge = Callable[[object, object, int, Sequence[int], Sequence[DietPost]], Awaitable[str]]


class DietScheduler:
    def __init__(
        self, store: SQLiteDietStore, get_guild: Callable[[int], object | None], *,
        zone: ZoneInfo | None = None, judge: Judge | None = None,
    ) -> None:
        self.store = store
        self.get_guild = get_guild
        self.zone = zone or DEFAULT_ZONE
        self.judge = judge

    async def tick(self, now: datetime) -> None:
        """Run every step that is due now, for every server with a channel and a role."""
        configured = await asyncio.to_thread(self.store.configured)
        for guild_id, channel_id, role_id in configured:
            try:
                await self._server(guild_id, channel_id, role_id, now)
            except Exception:  # noqa: BLE001 - one server never stops the others
                LOGGER.warning("diet_step_failed")

    async def _server(self, guild_id: int, channel_id: int, role_id: int, now: datetime) -> None:
        local = now.astimezone(self.zone)
        day = local.date().isoformat()
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        done = await asyncio.to_thread(self.store.done, guild_id, day)
        for stage, at, grace in STEPS:
            start = midnight.replace(hour=at.hour, minute=at.minute)
            if local < start:
                return
            if stage in done:
                continue
            late = grace is not None and local >= start + grace
            claimed = await asyncio.to_thread(
                self.store.claim, guild_id, day, stage, "skipped_late" if late else "running", now,
            )
            if not claimed:
                continue
            if late:
                LOGGER.info("diet_run stage=%s outcome=skipped_late", stage)
                continue
            outcome = await self._run(stage, guild_id, channel_id, role_id, midnight, now)
            await asyncio.to_thread(self.store.finish, guild_id, day, stage, outcome)

    async def _run(
        self, stage: str, guild_id: int, channel_id: int, role_id: int, midnight: datetime,
        now: datetime,
    ) -> str:
        guild = self.get_guild(guild_id)
        if guild is None:
            return self._log(stage, "no_guild")
        channel = guild.get_channel(channel_id)
        if channel is None or not valid_channel(guild, channel_id):
            return self._log(stage, "no_channel")
        role = guild.get_role(role_id)
        if role is None:
            return self._log(stage, "no_role")
        if stage == "call":
            text = localize(guild_id, CALL.format(role=f"<@&{role_id}>"))
            return await self._send(stage, channel, text, discord.AllowedMentions(
                everyone=False, users=False, roles=[role]))
        try:
            members = await role_members(guild, role_id)
            posts = await day_posts(channel, midnight.astimezone(UTC), now)
        except (discord.DiscordException, OSError):
            return self._log(stage, "read_failed")
        posted = {post.author_id for post in posts}
        missing = [member for member in members if member not in posted]
        if stage == "nag":
            if not missing:
                return self._log(stage, "all_posted", members=len(members))
            shown = missing[:NAG_LIMIT]
            mentions = " ".join(f"<@{member}>" for member in shown)
            if len(missing) > len(shown):
                mentions += f" 외 {len(missing) - len(shown)}명"
            text = localize(guild_id, NAG.format(members=mentions))
            return await self._send(stage, channel, text, discord.AllowedMentions(
                everyone=False, roles=False, users=[discord.Object(id=member) for member in shown]),
                members=len(members), missing=len(missing))
        if self.judge is None:
            return self._log(stage, "unavailable")
        outcome = await self.judge(guild, channel, role_id, missing,
                                   [post for post in posts if post.author_id in set(members)])
        return self._log(stage, outcome, members=len(members), missing=len(missing))

    async def _send(self, stage: str, channel: object, text: str,
                    mentions: discord.AllowedMentions, **counts: int) -> str:
        try:
            await channel.send(text, allowed_mentions=mentions)
        except (discord.DiscordException, OSError):
            return self._log(stage, "send_failed", **counts)
        return self._log(stage, "posted", **counts)

    @staticmethod
    def _log(stage: str, outcome: str, **counts: int) -> str:
        extra = "".join(f" {name}={value}" for name, value in sorted(counts.items()))
        LOGGER.info("diet_run stage=%s outcome=%s%s", stage, outcome, extra)
        return outcome
