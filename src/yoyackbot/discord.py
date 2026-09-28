"""Discord Gateway entry point and conservative message boundary."""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

import discord
from discord import app_commands

from yoyackbot.channel_config import MemoryWatchStore, WatchStore, install_channel_commands
from yoyackbot.config import Settings
from yoyackbot.domain import RangeRequest
from yoyackbot.parser import (
    HELP_TEXT,
    CommandLimitError,
    CommandSyntaxError,
    RouteKind,
    route_trigger,
)
from yoyackbot.range_request import resolve_range
from yoyackbot.watch_gate import UNAVAILABLE_NOTICE, ChannelLease, WatchGate
from yoyackbot.watch_store import SQLiteWatchStore

LOGGER = logging.getLogger(__name__)
PREVIEW_NOTICE = "요약 요청을 해석했소. 실제 요약 기능은 아직 준비 중이오."


class MessageCandidate(Protocol):
    guild: object | None
    channel: object
    author: object
    webhook_id: int | None
    type: discord.MessageType


class MessageClass(Enum):
    HUMAN_TEXT = "human_text"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    BOT = "bot"
    WEBHOOK = "webhook"
    SYSTEM = "system"


def classify_message(message: MessageCandidate) -> MessageClass:
    """Classify at ingress without reading or logging the message body."""
    if message.guild is None or getattr(message.channel, "type", None) is not discord.ChannelType.text:
        return MessageClass.UNSUPPORTED_CHANNEL
    if message.webhook_id is not None:
        return MessageClass.WEBHOOK
    if getattr(message.author, "bot", False):
        return MessageClass.BOT
    if message.type not in {discord.MessageType.default, discord.MessageType.reply}:
        return MessageClass.SYSTEM
    return MessageClass.HUMAN_TEXT


def required_intents() -> discord.Intents:
    """Request only guild, guild-message, and message-content events."""
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    return intents


class YoYackClient(discord.Client):
    def __init__(
        self,
        *,
        observe_channel_id: int | None = None,
        watch_store: WatchStore | None = None,
        dev_guild_id: int | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(intents=required_intents(), member_cache_flags=discord.MemberCacheFlags.none())
        self.observe_channel_id = observe_channel_id
        self.ready_event = asyncio.Event()
        self.accepted_events = 0
        self.nonempty_content_events = 0
        self.connection_count = 0
        self.watch_store = watch_store or MemoryWatchStore()
        self.watch_gate = WatchGate(self.watch_store)
        self.dev_guild_id = dev_guild_id
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self._synced_guild_ids: set[int] = set()
        self.tree = app_commands.CommandTree(self)
        install_channel_commands(self.tree, self.watch_store)

    async def setup_hook(self) -> None:
        if self.dev_guild_id is not None:
            await self._sync_guild_commands(discord.Object(id=self.dev_guild_id))
        else:
            commands = await self.tree.sync()
            LOGGER.info("commands_synced count=%d", len(commands))

    async def _sync_guild_commands(self, guild: discord.abc.Snowflake) -> None:
        if guild.id in self._synced_guild_ids:
            return
        self.tree.copy_global_to(guild=guild)
        commands = await self.tree.sync(guild=guild)
        self._synced_guild_ids.add(guild.id)
        LOGGER.info("commands_synced count=%d", len(commands))

    async def on_ready(self) -> None:
        self.connection_count += 1
        self.ready_event.set()
        LOGGER.info("gateway_ready guild_count=%d", len(self.guilds))
        if self.dev_guild_id is not None:
            for guild in self.guilds:
                try:
                    await self._sync_guild_commands(guild)
                except discord.HTTPException:
                    LOGGER.exception("guild_commands_sync_failed")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if self.dev_guild_id is not None:
            try:
                await self._sync_guild_commands(guild)
            except discord.HTTPException:
                LOGGER.exception("guild_commands_sync_failed")

    async def on_resumed(self) -> None:
        LOGGER.info("gateway_resumed")

    async def on_disconnect(self) -> None:
        LOGGER.info("gateway_disconnected")

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        try:
            if self.watch_store.remove_channel(channel.guild.id, channel.id):
                LOGGER.info("watched_channel_deleted")
        except Exception:
            LOGGER.exception("watched_channel_delete_cleanup_failed")

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        try:
            self.watch_store.remove_guild(guild.id)
            LOGGER.info("watched_guild_removed")
        except Exception:
            LOGGER.exception("watched_guild_cleanup_failed")

    async def on_message(self, message: discord.Message) -> None:
        if classify_message(message) is not MessageClass.HUMAN_TEXT:
            return
        self.accepted_events += 1
        if message.content:
            self.nonempty_content_events += 1
        if self.observe_channel_id is not None and message.channel.id == self.observe_channel_id:
            LOGGER.info("gateway_test_human_event has_content=%s", bool(message.content))
        route = route_trigger(message.content)
        if route.kind is RouteKind.HELP:
            await message.channel.send(HELP_TEXT, allowed_mentions=discord.AllowedMentions.none())
            return
        assert message.guild is not None
        if route.kind is RouteKind.SUMMARY:
            accepted_at = self.clock()

            async def send_notice(notice: str) -> None:
                await message.channel.send(notice, allowed_mentions=discord.AllowedMentions.none())

            async def handle_request(lease: ChannelLease) -> None:
                if self.settings is None:
                    await send_notice(UNAVAILABLE_NOTICE)
                    return
                try:
                    request = resolve_range(
                        route.options,
                        self.settings,
                        accepted_at,
                        trigger_message_id=getattr(message, "id", None),
                    )
                except (CommandSyntaxError, CommandLimitError) as exc:
                    await send_notice(str(exc))
                    return
                await self.on_summary_request(message, request, lease)

            await self.watch_gate.request(
                message.guild.id,
                message.channel.id,
                is_help=False,
                help_reply=lambda: send_notice(HELP_TEXT),
                unwatched_reply=send_notice,
                unavailable_reply=send_notice,
                summarize=handle_request,
            )
            return
        await self.watch_gate.ingest(
            message.guild.id,
            message.channel.id,
            message,
            self.on_watched_message,
        )

    async def on_watched_message(self, message: discord.Message, lease: ChannelLease) -> None:
        """Cache ingestion hook; persistence is implemented in 0.3.0."""

    async def on_summary_request(
        self, message: discord.Message, request: RangeRequest, lease: ChannelLease
    ) -> None:
        """Acknowledge parsed commands until the summary workflow is implemented."""
        LOGGER.info("summary_request_parsed kind=%s", request.kind.value)
        await message.channel.send(PREVIEW_NOTICE, allowed_mentions=discord.AllowedMentions.none())


async def run_gateway(
    settings: Settings,
    *,
    smoke_seconds: float | None = None,
    observe_channel_id: int | None = None,
) -> None:
    """Run the gateway; smoke mode closes after a bounded connection check."""
    client = YoYackClient(
        observe_channel_id=observe_channel_id,
        watch_store=SQLiteWatchStore(settings.database_path),
        dev_guild_id=settings.dev_guild_id,
        settings=settings,
    )
    async with client:
        if smoke_seconds is None:
            await client.start(settings.discord_bot_token)
            return
        task = asyncio.create_task(client.start(settings.discord_bot_token))
        try:
            ready = asyncio.create_task(client.ready_event.wait())
            done, _ = await asyncio.wait({ready, task}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
            if ready not in done:
                raise TimeoutError("Gateway did not become ready")
            await asyncio.sleep(smoke_seconds)
            LOGGER.info(
                "gateway_smoke_ok accepted_events=%d nonempty_content_events=%d",
                client.accepted_events,
                client.nonempty_content_events,
            )
        finally:
            ready.cancel()
            await client.close()
            if not task.done():
                task.cancel()
            await asyncio.gather(ready, task, return_exceptions=True)
