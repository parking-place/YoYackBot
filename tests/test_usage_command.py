"""`!!요약좀 사용량` routing, wording, and confirmed usage-limit notices (T101-P2)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.codex import CodexFailure, classify_cli_failure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import CollectionOutcome
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.parser import RouteKind, route_trigger
from yoyackbot.state import ChannelStates
from yoyackbot.usage import (
    USAGE_EXHAUSTED_NOTICE,
    USAGE_UNAVAILABLE_NOTICE,
    UsageSnapshot,
    UsageUnavailable,
    usage_message,
)
from yoyackbot.watch_gate import UNAVAILABLE_NOTICE, UNWATCHED_NOTICE
from yoyackbot.workflow import SummaryWorkflow

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def request() -> SummaryRequest:
    return SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW,
                                                start=NOW - timedelta(minutes=5)))


def channel() -> object:
    return SimpleNamespace(type=discord.ChannelType.text, id=2,
                           guild=SimpleNamespace(id=1), name="합성")


PLENTY = "Codex의 기운을 살펴보았소.\n\n5시간 한도는 74% 남았소.\n주간 한도는 82% 남았소.\n\n" \
    "아직 요약을 정상화하기엔 넉넉하오."
STRAINED = "Codex의 기운을 살펴보았소.\n\n5시간 한도는 74% 남았소.\n주간 한도는 9% 남았소.\n\n" \
    "요약 정상화가 버겁기 시작했소."


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("!!요약좀 사용량", RouteKind.USAGE),
        ("신창섭아 !!요약좀   사용량  ", RouteKind.USAGE),
        ("!!요약좀 사용량 도움", RouteKind.HELP),
        ("!!요약좀 사용량 !!요약좀 도움", RouteKind.HELP),
        ("!!요약좀 사용량 부탁하오", RouteKind.SUMMARY),
        ("!!요약좀 3시간 사용량", RouteKind.SUMMARY),
        ("!!요약좀 사용량좀", RouteKind.SUMMARY),
        ("사용량 !!요약좀", RouteKind.SUMMARY),
    ],
)
def test_usage_is_one_exact_word_and_help_keeps_priority(content: str, kind: RouteKind) -> None:
    assert route_trigger(content).kind is kind


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (UsageSnapshot(74, 82), PLENTY),
        (UsageSnapshot(74, 9), STRAINED),
        (UsageSnapshot(10, 100), STRAINED.replace("74", "10").replace("9%", "100%")),
        (UsageSnapshot(0, 100), STRAINED.replace("74", "0").replace("9%", "100%")),
        (UsageSnapshot(11, 11), PLENTY.replace("74", "11").replace("82", "11")),
        (UsageSnapshot(None, 82), ("Codex의 기운을 살펴보았소.\n\n주간 한도는 82% 남았소.\n\n"
                                   "아직 요약을 정상화하기엔 넉넉하오.")),
        (UsageSnapshot(None, 6), ("Codex의 기운을 살펴보았소.\n\n주간 한도는 6% 남았소.\n\n"
                                  "요약 정상화가 버겁기 시작했소.")),
    ],
)
def test_usage_wording_and_warning_boundary(snapshot: UsageSnapshot, expected: str) -> None:
    assert usage_message(snapshot) == expected


def usage_message_event(channel_id: int = 99, content: str = "!!요약좀 사용량") -> SimpleNamespace:
    return SimpleNamespace(
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(type=discord.ChannelType.text, id=channel_id, send=AsyncMock()),
        author=SimpleNamespace(bot=False, id=5),
        webhook_id=None,
        type=discord.MessageType.default,
        content=content,
    )


class Reader:
    def __init__(self, result: UsageSnapshot | Exception) -> None:
        self.result = result
        self.calls = 0

    async def __call__(self) -> UsageSnapshot:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NoWorkflow:
    async def run(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("usage must not start a summary job")

    async def shutdown(self) -> None:
        return None


@pytest.mark.parametrize(
    ("watched", "result", "expected", "reads"),
    [
        (True, UsageSnapshot(74, 82), PLENTY, 1),
        (True, UsageSnapshot(74, 9), STRAINED, 1),
        (True, UsageUnavailable("private raw detail"), USAGE_UNAVAILABLE_NOTICE, 1),
        (False, UsageSnapshot(74, 82), UNWATCHED_NOTICE, 0),
    ],
)
def test_gateway_answers_usage_only_in_watched_channels(
    watched: bool, result: UsageSnapshot | Exception, expected: str, reads: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        store = MemoryWatchStore()
        store.replace(1, frozenset({99}) if watched else frozenset())
        reader = Reader(result)
        client = YoYackClient(
            watch_store=store, usage_reader=reader, summary_workflow=NoWorkflow(),  # type: ignore[arg-type]
        )
        try:
            event = usage_message_event()
            await client.on_message(event)
            event.channel.send.assert_awaited_once()
            args, kwargs = event.channel.send.await_args
            assert args == (expected,)
            assert kwargs["allowed_mentions"].to_dict()["parse"] == []
            assert reader.calls == reads
        finally:
            await client.close()

    asyncio.run(scenario())
    assert "private raw detail" not in caplog.text


def test_usage_lookup_failure_of_watch_settings_is_reported() -> None:
    class Broken(MemoryWatchStore):
        def snapshot(self, guild_id: int):  # type: ignore[override]
            raise RuntimeError("database locked")

    async def scenario() -> None:
        reader = Reader(UsageSnapshot(74, 82))
        client = YoYackClient(watch_store=Broken(), usage_reader=reader)
        try:
            event = usage_message_event()
            await client.on_message(event)
            assert event.channel.send.await_args.args == (UNAVAILABLE_NOTICE,)
            assert reader.calls == 0
        finally:
            await client.close()

    asyncio.run(scenario())


def test_usage_reads_do_not_overlap() -> None:
    async def scenario() -> None:
        active = 0
        peak = 0

        async def reader() -> UsageSnapshot:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return UsageSnapshot(None, 50)

        client = YoYackClient(usage_reader=reader)
        try:
            replies = await asyncio.gather(*(client.usage_reply() for _ in range(5)))
        finally:
            await client.close()
        assert peak == 1 and len(set(replies)) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("ERROR: Usage limit reached. You've reached your usage limit.", CodexFailure.USAGE_LIMIT),
        ("You've hit your usage limit. Try again later.", CodexFailure.USAGE_LIMIT),
        ('{"type":"usage_limit_reached","status":429}', CodexFailure.USAGE_LIMIT),
        ("error code usage_limit_exceeded", CodexFailure.USAGE_LIMIT),
        ("workspace_member_credits_depleted", CodexFailure.USAGE_LIMIT),
        ("insufficient_quota", CodexFailure.USAGE_LIMIT),
        ("HTTP 429 Too Many Requests", CodexFailure.LIMIT),
        ("rate_limit_exceeded: retry", CodexFailure.LIMIT),
        ("Server overloaded; retry later.", CodexFailure.LIMIT),
        ("Failed to refresh token", CodexFailure.AUTH),
        ("request timed out", CodexFailure.PROCESS),
        ("model_not_found", CodexFailure.MODEL),
    ],
)
def test_only_confirmed_account_exhaustion_is_a_usage_limit(
    diagnostic: str, expected: CodexFailure,
) -> None:
    assert classify_cli_failure(1, diagnostic) is expected


def summary_workflow(failures: list[CodexFailure], states: ChannelStates) -> tuple:
    class Collector:
        async def collect(self, _channel, *, guild_id, channel_id, request, **_kwargs):
            row = MessageRecord(1, guild_id, channel_id, 3, "합성 화자", "합성 대화",
                                request.accepted_at - timedelta(minutes=1))
            return CollectionOutcome((row,), 0, request.accepted_at, 0, False)

    class Engine:
        async def summarize(self, _messages, **_kwargs):
            if failures:
                raise CodexRunError(failures.pop(0))
            return SummaryResult("합성 대화를 정리하였소.", "synthetic", 1)

    class Publisher:
        published = 0

        async def publish(self, request, _result, _messages):
            Publisher.published += 1
            return PublicationReceipt((request.channel_id + 100,), NOW)

    return SummaryWorkflow(Collector(), Engine(), Publisher(), states), Publisher  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("failure", "notice"),
    [
        (CodexFailure.USAGE_LIMIT, USAGE_EXHAUSTED_NOTICE),
        (CodexFailure.LIMIT, message_for(FailureKind.MODEL)),
        (CodexFailure.AUTH, message_for(FailureKind.MODEL)),
        (CodexFailure.TIMEOUT, message_for(FailureKind.MODEL)),
        (CodexFailure.MODEL, message_for(FailureKind.MODEL)),
    ],
)
def test_usage_exhaustion_notice_is_exact_and_failure_allows_retry(
    failure: CodexFailure, notice: str, tmp_path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        cooldowns = SQLiteCooldownStore(tmp_path / "cooldown.db", duration_seconds=300)
        states = ChannelStates(cooldowns)
        workflow, publisher = summary_workflow([failure], states)
        notices: list[str] = []

        async def send(value: str) -> None:
            notices.append(value)

        lease = SimpleNamespace(valid=lambda: True)
        await workflow.run(request(), channel(), lease, send)  # type: ignore[arg-type]
        assert notices == [notice]
        assert publisher.published == 0
        assert (await states.admit(1, 2)).kind.value == "accepted"
        await states.finish(1, 2)
        await workflow.run(request(), channel(), lease, send)  # type: ignore[arg-type]
        assert publisher.published == 1 and notices[1:] == []
        assert (await states.admit(1, 2)).kind.value == "cooldown"

    asyncio.run(scenario())
    assert f'"failure_detail":"{failure.value}"' in caplog.text
