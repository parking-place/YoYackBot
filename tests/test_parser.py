"""Included trigger and help priority contracts."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.discord import PREVIEW_NOTICE, YoYackClient
from yoyackbot.domain import SummaryMode
from yoyackbot.parser import (
    HELP_TEXT,
    CommandLimitError,
    CommandSyntaxError,
    OptionKind,
    ParsedOption,
    RouteKind,
    help_text,
    parse_option,
    route_trigger,
    validate_option,
)
from yoyackbot.state import ChannelStates, ChannelStatus
from yoyackbot.watch_gate import UNWATCHED_NOTICE
from yoyackbot.workflow import SummaryWorkflow


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
        "`!!요약좀 30일`",
        "`!!요약좀 1주`",
        "`/채널 설정`",
        "`!!요약좀 오늘 자세히`",
        "`!!요약좀 5시간 짧게`",
        "`!!요약좀 사용량`",
        "`!!요약좀 상태`",
        "`!!요약좀 채널`",
    ):
        assert example in HELP_TEXT
    assert "요약을 시작하면 범위를 먼저 알려주고" in HELP_TEXT and "준비 중이라고 답하오" in HELP_TEXT
    assert "범위를 생략하면 최근 1시간" in HELP_TEXT and "모든 서버가 함께 쓰는 파일" in HELP_TEXT
    assert len(HELP_TEXT) < 2000
    assert "기간 요약은 최대 30일까지 가능하오." in HELP_TEXT


def test_help_uses_effective_day_limit_when_operator_lowers_it() -> None:
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "test-token", "YOYACK_MAX_DAYS": "7",
    })
    text = help_text(settings)
    assert "`!!요약좀 7일`" in text
    assert "`!!요약좀 30일`" not in text
    assert "일 단위 요청은 최대 7일까지 가능하오." in text
    assert validate_option(parse_option("7일"), settings).value == 7
    with pytest.raises(CommandLimitError):
        validate_option(parse_option("8일"), settings)


def test_discord_help_route_sends_effective_limit_without_mention(tmp_path) -> None:
    async def scenario() -> None:
        settings = Settings.from_environment({
            "DISCORD_BOT_TOKEN": "test-token", "YOYACK_MAX_DAYS": "7",
            "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        })
        sent = AsyncMock()
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent)
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1), channel=channel,
            author=SimpleNamespace(bot=False), webhook_id=None,
            type=discord.MessageType.default, content="!!요약좀 도움",
        )
        client = YoYackClient(settings=settings, watch_store=MemoryWatchStore())
        try:
            await client.on_message(message)
            assert sent.await_args.args[0] == help_text(settings)
            mentions = sent.await_args.kwargs["allowed_mentions"]
            assert not mentions.everyone and not mentions.users and not mentions.roles
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("", ParsedOption(OptionKind.HOURS, 1, explicit=False)),
        ("3", ParsedOption(OptionKind.HOURS, 3)),
        ("30분", ParsedOption(OptionKind.MINUTES, 30)),
        ("2시간", ParsedOption(OptionKind.HOURS, 2)),
        ("100개", ParsedOption(OptionKind.COUNT, 100)),
        ("오늘", ParsedOption(OptionKind.TODAY, None)),
        ("2일", ParsedOption(OptionKind.DAYS, 2)),
        ("1주", ParsedOption(OptionKind.WEEKS, 1)),
        ("30분 부탁하오", ParsedOption(OptionKind.MINUTES, 30)),
        ("5", ParsedOption(OptionKind.HOURS, 5)),
        ("5분", ParsedOption(OptionKind.MINUTES, 5)),
        ("5개", ParsedOption(OptionKind.COUNT, 5)),
    ],
)
def test_all_supported_option_forms(option: str, expected: ParsedOption) -> None:
    assert parse_option(option) == expected


@pytest.mark.parametrize(
    "option",
    [
        "2시간 100개",
        "어제쯤",
        "1.5시간",
        "오늘 1일",
        "5광년",
        "3시간 !!요약좀",
        "999999999999999999999시간",
    ],
)
def test_conflicting_or_unknown_options_are_rejected(option: str) -> None:
    with pytest.raises(CommandSyntaxError):
        parse_option(option)


@pytest.mark.parametrize(
    ("unit", "maximum"),
    [("분", 1440), ("시간", 168), ("일", 30), ("주", 4), ("개", 1000)],
)
def test_each_numeric_limit_has_closed_upper_boundary(unit: str, maximum: int) -> None:
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"})
    for value in (maximum - 1, maximum):
        assert validate_option(parse_option(f"{value}{unit}"), settings).value == value
    for value in (0, maximum + 1):
        with pytest.raises(CommandLimitError, match="!!요약좀 도움"):
            validate_option(parse_option(f"{value}{unit}"), settings)


def test_limits_are_configurable_and_do_not_truncate_four_weeks_to_cache_retention() -> None:
    settings = Settings.from_environment(
        {"DISCORD_BOT_TOKEN": "test-token", "YOYACK_MAX_WEEKS": "2", "YOYACK_MAX_DAYS": "3"}
    )
    assert validate_option(parse_option("2주"), settings).value == 2
    assert validate_option(parse_option("3일"), settings).value == 3
    with pytest.raises(CommandLimitError, match="2까지"):
        validate_option(parse_option("3주"), settings)

    defaults = Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"})
    assert defaults.cache_retention_days == 30
    assert validate_option(parse_option("4주"), defaults).value == 4
    with pytest.raises(CommandLimitError):
        validate_option(parse_option("5주"), defaults)


@pytest.mark.parametrize("option", ["-1시간", "+1시간", "1.5시간", "99광년", "999999999999999999999주"])
def test_invalid_numeric_spelling_stops_before_validation(option: str) -> None:
    with pytest.raises(CommandSyntaxError):
        parse_option(option)


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


def test_all_command_forms_reach_normalized_request_and_invalid_options_stop() -> None:
    async def scenario() -> None:
        store = MemoryWatchStore()
        store.replace(1, frozenset({99}))
        sent = AsyncMock()
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent)
        accepted = datetime(2026, 9, 28, 12, tzinfo=UTC)
        requests = []

        class SpyClient(YoYackClient):
            async def on_summary_request(self, message, request, lease, *, mode, scope) -> None:
                assert lease.valid()
                assert mode is SummaryMode.NORMAL
                requests.append(request)

        client = SpyClient(
            watch_store=store,
            settings=Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"}),
            clock=lambda: accepted,
        )

        def message(content: str) -> SimpleNamespace:
            return SimpleNamespace(
                id=500,
                guild=SimpleNamespace(id=1),
                channel=channel,
                author=SimpleNamespace(bot=False),
                webhook_id=None,
                type=discord.MessageType.default,
                content=content,
            )

        try:
            for content in (
                "!!요약좀", "!!요약좀 3", "!!요약좀 30분", "!!요약좀 2시간",
                "!!요약좀 100개", "!!요약좀 오늘", "!!요약좀 2일", "!!요약좀 1주",
            ):
                await client.on_message(message(content))
            assert len(requests) == 8
            assert all(request.accepted_at == accepted and request.trigger_message_id == 500 for request in requests)
            assert requests[4].count == 100 and requests[4].start is None
            assert requests[5].start == datetime(2026, 9, 27, 15, tzinfo=UTC)

            await client.on_message(message("!!요약좀 0분"))
            assert "!!요약좀 도움" in sent.await_args.args[0]
            await client.on_message(message("!!요약좀 1.5시간"))
            assert "!!요약좀 도움" in sent.await_args.args[0]
            assert len(requests) == 8

            store.replace(1, frozenset())
            await client.on_message(message("!!요약좀 3"))
            assert sent.await_args.args[0] == UNWATCHED_NOTICE
            assert len(requests) == 8
            await client.on_message(message("!!요약좀 도움"))
            assert sent.await_args.args[0] == HELP_TEXT
        finally:
            await client.close()

    asyncio.run(scenario())


def test_preview_reply_never_claims_a_model_summary() -> None:
    async def scenario() -> None:
        store = MemoryWatchStore()
        store.replace(1, frozenset({99}))
        sent = AsyncMock()
        client = YoYackClient(
            watch_store=store,
            settings=Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"}),
        )
        message = SimpleNamespace(
            id=500,
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent),
            author=SimpleNamespace(bot=False),
            webhook_id=None,
            type=discord.MessageType.default,
            content="!!요약좀 5분",
        )
        try:
            await client.on_message(message)
            sent.assert_awaited_once()
            assert sent.await_args.args[0] == PREVIEW_NOTICE
            assert sent.await_args.kwargs["allowed_mentions"].everyone is False
        finally:
            await client.close()

    asyncio.run(scenario())


def test_help_is_available_while_summarizing_and_during_success_cooldown(tmp_path) -> None:
    async def scenario() -> None:
        now = datetime(2026, 9, 28, 12, tzinfo=UTC)
        watch = MemoryWatchStore()
        watch.replace(1, frozenset({99}))
        sent = AsyncMock()
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent)
        message = SimpleNamespace(
            id=500, guild=SimpleNamespace(id=1), channel=channel,
            author=SimpleNamespace(bot=False), webhook_id=None,
            type=discord.MessageType.default, content="!!요약좀 도움",
        )

        class Unused:
            async def collect(self, *_args, **_kwargs):
                raise AssertionError("Help must not enter collection")

            async def summarize(self, *_args, **_kwargs):
                raise AssertionError("Help must not enter model")

            async def publish(self, *_args, **_kwargs):
                raise AssertionError("Help must not enter publisher")

        unused = Unused()
        states = ChannelStates(SQLiteCooldownStore(tmp_path / "state.db"), clock=lambda: now)
        workflow = SummaryWorkflow(unused, unused, unused, states)  # type: ignore[arg-type]
        client = YoYackClient(
            watch_store=watch, summary_workflow=workflow,
            settings=Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"}),
        )
        try:
            assert await states.begin(1, 99)
            await client.on_message(message)
            assert await states.status(1, 99) is ChannelStatus.SUMMARIZING
            await states.finish_success(1, 99, now)
            await client.on_message(message)
            assert await states.status(1, 99) is ChannelStatus.COOLDOWN
            assert [call.args[0] for call in sent.await_args_list] == [HELP_TEXT, HELP_TEXT]
        finally:
            await client.close()

    asyncio.run(scenario())
