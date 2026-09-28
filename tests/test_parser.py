"""Included trigger and help priority contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.discord import YoYackClient
from yoyackbot.parser import HELP_TEXT, RouteKind, route_trigger


def test_included_trigger_uses_only_text_after_first_marker() -> None:
    assert route_trigger("ordinary conversation").kind is RouteKind.NONE
    assert route_trigger("신창섭아 !!요약좀").options == ""
    assert route_trigger("지금까지 대화 !!요약좀 3시간").options == "3시간"
    repeated = route_trigger("!!요약좀 3 !!요약좀 4")
    assert repeated.kind is RouteKind.SUMMARY and repeated.options == "3" and repeated.repeated


def test_help_has_priority_even_with_repeated_trigger() -> None:
    assert route_trigger("!!요약좀 도움").kind is RouteKind.HELP
    assert route_trigger("신창섭아 !!요약좀 2시간 !!요약좀 도움").kind is RouteKind.HELP
    assert route_trigger("!!요약좀 2시간 도움말").kind is RouteKind.HELP
    assert route_trigger("!!요약좀 도움을 부탁하오").kind is RouteKind.SUMMARY


def test_help_examples_cover_all_supported_forms() -> None:
    for example in (
        "`!!요약좀`",
        "`!!요약좀 3`",
        "`!!요약좀 30분`",
        "`!!요약좀 2시간`",
        "`!!요약좀 100개`",
        "`!!요약좀 오늘`",
        "`!!요약좀 2일`",
        "`!!요약좀 1주`",
        "`/채널 설정`",
    ):
        assert example in HELP_TEXT
    assert len(HELP_TEXT) < 2000


def test_help_in_unwatched_channel_sends_without_ingestion() -> None:
    async def scenario() -> None:
        sent = AsyncMock()
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent)
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=channel,
            author=SimpleNamespace(bot=False),
            webhook_id=None,
            type=discord.MessageType.default,
            content="신창섭아 !!요약좀 도움",
        )
        called: list[int] = []

        class SpyClient(YoYackClient):
            async def on_watched_message(self, message, lease) -> None:
                called.append(message.channel.id)

        client = SpyClient(watch_store=MemoryWatchStore())
        try:
            await client.on_message(message)
            sent.assert_awaited_once()
            assert sent.await_args.args[0] == HELP_TEXT
            assert called == []
        finally:
            await client.close()

    asyncio.run(scenario())
