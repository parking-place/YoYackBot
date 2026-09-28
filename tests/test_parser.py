"""Included trigger and help priority contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.parser import (
    HELP_TEXT,
    CommandLimitError,
    CommandSyntaxError,
    OptionKind,
    ParsedOption,
    RouteKind,
    parse_option,
    route_trigger,
    validate_option,
)


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
    [("분", 1440), ("시간", 168), ("일", 7), ("주", 4), ("개", 1000)],
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
    assert defaults.cache_retention_days == 7
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
