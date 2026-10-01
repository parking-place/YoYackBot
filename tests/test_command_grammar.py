"""`!!요약좀 [range] [length] [request...]` with short as the default (T110-P1)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import SummaryMode
from yoyackbot.parser import (
    REQUEST_TOO_LONG_NOTICE,
    USAGE_NOTICE,
    CommandLimitError,
    CommandSyntaxError,
    RouteKind,
    clean_request_note,
    parse_summary_command,
    route_trigger,
)
from yoyackbot.range_request import resolve_range
from yoyackbot.scope import busy_notice, describe_range, start_notice

SETTINGS = Settings.from_environment({"DISCORD_BOT_TOKEN": "synthetic"})
NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
S, L, D = SummaryMode.SHORT, SummaryMode.LONG, SummaryMode.DETAILED


@pytest.mark.parametrize(
    ("options", "range_text", "mode", "note"),
    [
        ("", "", S, None),
        ("시간순으로", "", S, "시간순으로"),
        ("30분 길게 가람 얘기 위주로", "30분", L, "가람 얘기 위주로"),
        ("오늘 자세히 결정만 따로 모아줘", "오늘", D, "결정만 따로 모아줘"),
        ("3 부탁하오", "3", S, None),
        ("2분 길게 시간순으로 해줘", "2분", L, "시간순으로 해줘"),
        ("3 시간 짧게", "3 시간", S, None),
        ("100개 표로 정리해줘", "100개", S, "표로 정리해줘"),
        ("길게", "", L, None),
        ("자세히 부탁하오", "", D, None),
        ("짧게 결론부터", "", S, "결론부터"),
        ("3 시간순으로", "3", S, "시간순으로"),
    ],
)
def test_parts_are_read_in_order(options, range_text, mode, note) -> None:
    command = parse_summary_command(options)
    assert (command.range_text, command.mode, command.note) == (range_text, mode, note)


RANGES = ["", "3", "30분", "2시간", "100개", "오늘", "3일", "1주"]


@pytest.mark.parametrize("range_text", RANGES)
@pytest.mark.parametrize(("word", "mode"), [("", S), ("짧게", S), ("길게", L), ("자세히", D)])
@pytest.mark.parametrize("note", ["", "시간순으로 해줘"])
def test_length_and_note_never_change_the_range(range_text, word, mode, note) -> None:
    command = parse_summary_command(" ".join(part for part in (range_text, word, note) if part))
    assert command.mode is mode and command.note == (note or None)
    assert resolve_range(command.range_text, SETTINGS, NOW) == resolve_range(range_text, SETTINGS, NOW)


@pytest.mark.parametrize(
    ("mode", "start", "busy"),
    [
        (S, "3시간 채팅을 요약해보겠소.", "현재 3시간 분 채팅을 요약중이오."),
        (L, "3시간 채팅을 길게 요약해보겠소.", "현재 3시간 분 채팅을 길게 요약중이오."),
        (D, "3시간 채팅을 자세히 요약해보겠소.", "현재 3시간 분 채팅을 자세히 요약중이오."),
    ],
)
def test_notice_mode_words(mode, start, busy) -> None:
    scope = describe_range("3", SETTINGS)
    assert start_notice(scope, mode) == start
    assert busy_notice(scope, mode).splitlines()[0] == busy


@pytest.mark.parametrize(
    "options",
    ["자세히 2시간", "길게 30분", "길게 짧게로", "자세히 자세히", "짧게 길게", "오늘 길게 오늘",
     "사용량 알려줘", "상태 보여줘", "채널 목록", "2시간 채널", "1.5시간", "3 2시간",
     "시간순으로 자세히 해줘", "길게 3 시간"],
)
def test_misreadings_are_refused(options: str) -> None:
    with pytest.raises(CommandSyntaxError) as raised:
        parse_summary_command(options)
    assert str(raised.value) == USAGE_NOTICE


def test_help_and_exact_commands_keep_their_routes() -> None:
    assert route_trigger("!!요약좀 길게 도움").kind is RouteKind.HELP
    assert route_trigger("!!요약좀 사용량").kind is RouteKind.USAGE
    assert route_trigger("!!요약좀 상태").kind is RouteKind.STATUS
    assert route_trigger("!!요약좀 채널").kind is RouteKind.CHANNELS
    assert route_trigger("!!요약좀 2분 길게 시간순으로 해줘").kind is RouteKind.SUMMARY


def test_request_notes_are_cleaned() -> None:
    assert clean_request_note("  <@123> 가람\n얘기 @everyone  위주로\t ") == "가람 얘기 위주로"
    assert clean_request_note("<#45> <@&9>") is None
    assert clean_request_note("부탁하오") is None
    assert clean_request_note("가" * 200) == "가" * 200
    with pytest.raises(CommandLimitError) as raised:
        clean_request_note("가" * 201)
    assert str(raised.value) == REQUEST_TOO_LONG_NOTICE == "추가 요청은 200자까지만 알아듣겠소."


def test_gateway_carries_the_note_and_logs_only_its_length(caplog) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> list[tuple]:
        store = MemoryWatchStore()
        store.replace(1, frozenset({99}))
        seen: list[tuple] = []

        class Spy(YoYackClient):
            async def on_summary_request(self, message, request, lease, *, mode, scope, note=None):
                seen.append((request, mode, scope.text, note))
                await super().on_summary_request(message, request, lease, mode=mode,
                                                 scope=scope, note=note)

        class Workflow:
            requests: ClassVar[list] = []

            async def run(self, request, *_args):
                Workflow.requests.append(request)

            async def shutdown(self) -> None:
                return None

        sent = AsyncMock()
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent)
        client = Spy(watch_store=store, settings=SETTINGS, clock=lambda: NOW,
                     summary_workflow=Workflow())  # type: ignore[arg-type]
        try:
            for content in ("!!요약좀 2분 길게 시간순으로 해줘", "!!요약좀",
                            "!!요약좀 " + "가" * 201, "!!요약좀 자세히 2시간"):
                await client.on_message(SimpleNamespace(
                    id=500, guild=SimpleNamespace(id=1), channel=channel,
                    author=SimpleNamespace(bot=False, id=5), webhook_id=None,
                    type=discord.MessageType.default, content=content,
                ))
        finally:
            await client.close()
        assert [call.args[0] for call in sent.await_args_list] == [
            REQUEST_TOO_LONG_NOTICE, USAGE_NOTICE]
        assert [request.request_note for request in Workflow.requests] == ["시간순으로 해줘", None]
        assert Workflow.requests[0].mode is L and Workflow.requests[1].mode is S
        return seen

    seen = asyncio.run(scenario())
    assert seen[0][0].start == NOW - timedelta(minutes=2) and seen[0][2] == "2분"
    assert "시간순으로" not in caplog.text
    assert "has_request=True request_chars=8" in caplog.text
    assert "has_request=False request_chars=0" in caplog.text


def test_help_explains_lengths_and_request_notes() -> None:
    from yoyackbot.parser import HELP_TEXT

    for phrase in ("`!!요약좀` — 최근 1시간의 대화를 주제별로 짧게 요약하오.",
                   "모든 요약 끝에는 **요약창섭의 떡밥 한줄 평가**로 한줄 비평이 붙소.",
                   "형식·길이·말투·순서는 기본보다 그 말을 먼저 따르오.", "`!!요약좀 평가 빼줘`",
                   "기본은 짧게 요약하오.", "`!!요약좀 [범위] 길게`", "`!!요약좀 [범위] 자세히`",
                   "아주 길고 촘촘하게", "`짧게`를 붙여도 기본과 같소.",
                   "`!!요약좀 2분 길게 시간순으로 해줘`", "추가 요청은 200자까지이며",
                   "범위를 바꾸거나 없는 사실을 만들어 달라는 말은 듣지 않소"):
        assert phrase in HELP_TEXT
    assert "5시간 짧게" not in HELP_TEXT and len(HELP_TEXT) < 2000
