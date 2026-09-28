"""Discord Gateway entry point and conservative message boundary."""

import asyncio
import logging
from enum import Enum
from typing import Protocol

import discord
from discord import app_commands

from yoyackbot.channel_config import MemoryWatchStore, WatchStore, install_channel_commands
from yoyackbot.config import Settings

LOGGER = logging.getLogger(__name__)


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
    ) -> None:
        super().__init__(intents=required_intents(), member_cache_flags=discord.MemberCacheFlags.none())
        self.observe_channel_id = observe_channel_id
        self.ready_event = asyncio.Event()
        self.accepted_events = 0
        self.nonempty_content_events = 0
        self.connection_count = 0
        self.watch_store = watch_store or MemoryWatchStore()
        self.dev_guild_id = dev_guild_id
        self.tree = app_commands.CommandTree(self)
        install_channel_commands(self.tree, self.watch_store)

    async def setup_hook(self) -> None:
        if self.dev_guild_id is not None:
            guild = discord.Object(id=self.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
        else:
            commands = await self.tree.sync()
        LOGGER.info("commands_synced count=%d", len(commands))

    async def on_ready(self) -> None:
        self.connection_count += 1
        self.ready_event.set()
        LOGGER.info("gateway_ready guild_count=%d", len(self.guilds))

    async def on_resumed(self) -> None:
        LOGGER.info("gateway_resumed")

    async def on_disconnect(self) -> None:
        LOGGER.info("gateway_disconnected")

    async def on_message(self, message: discord.Message) -> None:
        if classify_message(message) is not MessageClass.HUMAN_TEXT:
            return
        self.accepted_events += 1
        if message.content:
            self.nonempty_content_events += 1
        if self.observe_channel_id is not None and message.channel.id == self.observe_channel_id:
            LOGGER.info("gateway_test_human_event has_content=%s", bool(message.content))
        # Watched-channel persistence is added in 0.3.0.


async def run_gateway(
    settings: Settings,
    *,
    smoke_seconds: float | None = None,
    observe_channel_id: int | None = None,
) -> None:
    """Run the gateway; smoke mode closes after a bounded connection check."""
    client = YoYackClient(
        observe_channel_id=observe_channel_id,
        dev_guild_id=settings.dev_guild_id,
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
