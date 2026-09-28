"""Ingress filtering and least-privilege Gateway settings."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.discord import MessageClass, YoYackClient, classify_message, required_intents


def sample_message(**changes: object) -> SimpleNamespace:
    attrs = {
        "guild": SimpleNamespace(id=1),
        "channel": SimpleNamespace(type=discord.ChannelType.text, id=99),
        "author": SimpleNamespace(bot=False),
        "webhook_id": None,
        "type": discord.MessageType.default,
        "content": "only synthetic content",
    }
    attrs.update(changes)
    return SimpleNamespace(**attrs)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, MessageClass.HUMAN_TEXT),
        ({"guild": None}, MessageClass.UNSUPPORTED_CHANNEL),
        ({"channel": SimpleNamespace(type=discord.ChannelType.public_thread)}, MessageClass.UNSUPPORTED_CHANNEL),
        ({"author": SimpleNamespace(bot=True)}, MessageClass.BOT),
        ({"webhook_id": 42}, MessageClass.WEBHOOK),
        ({"type": discord.MessageType.pins_add}, MessageClass.SYSTEM),
    ],
)
def test_ingress_classification(changes: dict[str, object], expected: MessageClass) -> None:
    assert classify_message(sample_message(**changes)) is expected


def test_only_required_intents_are_enabled() -> None:
    intents = required_intents()
    assert intents.guilds and intents.guild_messages and intents.message_content
    assert not intents.members and not intents.presences and not intents.dm_messages


def test_on_message_never_stores_or_logs_bot_events(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="yoyackbot.discord")
    async def scenario() -> None:
        client = YoYackClient(observe_channel_id=42)
        try:
            await client.on_message(sample_message(author=SimpleNamespace(bot=True)))
            assert client.accepted_events == 0
            await client.on_message(sample_message())
            assert client.accepted_events == 1
            assert client.nonempty_content_events == 1
            assert "gateway_test_human_event has_content=True" not in caplog.text
            await client.on_message(
                sample_message(channel=SimpleNamespace(type=discord.ChannelType.text, id=42))
            )
            assert "gateway_test_human_event has_content=True" in caplog.text
            assert "only synthetic content" not in caplog.text
        finally:
            await client.close()

    asyncio.run(scenario())


def test_gateway_handler_stops_watched_processing_after_removal() -> None:
    async def scenario() -> None:
        store = MemoryWatchStore()
        store.replace(1, frozenset({99}))
        delivered: list[int] = []

        class SpyClient(YoYackClient):
            async def on_watched_message(self, message, lease) -> None:
                assert lease.valid()
                delivered.append(message.channel.id)

        client = SpyClient(watch_store=store)
        try:
            await client.on_message(sample_message())
            assert delivered == [99]
            store.replace(1, frozenset())
            await client.on_message(sample_message())
            assert delivered == [99]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_development_commands_sync_to_each_guild_once() -> None:
    async def scenario() -> None:
        client = YoYackClient(dev_guild_id=1)
        tree = SimpleNamespace(copy_global_to=Mock(), sync=AsyncMock(return_value=[object()]))
        client.tree = tree
        try:
            await client.setup_hook()
            await client.on_guild_join(SimpleNamespace(id=2))
            await client.on_guild_join(SimpleNamespace(id=2))
            assert tree.sync.await_count == 2
            assert {call.kwargs["guild"].id for call in tree.sync.await_args_list} == {1, 2}
        finally:
            await client.close()

    asyncio.run(scenario())
