"""Every admitted request in a ready channel is told its range once, before the cache read
(T102-P3)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.backfill import NOT_READY_NOTICE
from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import EMPTY_NOTICE, CollectionOutcome
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryMode,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.job_queue import QueueFull
from yoyackbot.parser import OptionKind
from yoyackbot.scope import RangeScope
from yoyackbot.state import ChannelStates
from yoyackbot.usage import USAGE_EXHAUSTED_NOTICE
from yoyackbot.workflow import (
    INVALIDATED_NOTICE,
    QUEUE_CLOSED_NOTICE,
    QUEUE_FULL_NOTICE,
    SummaryWorkflow,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
TEN_DAYS = RangeScope(OptionKind.DAYS, 10)
START = "📝 10일 채팅을 요약해보겠소. ✍️"


def request(scope: RangeScope | None = TEN_DAYS,
            mode: SummaryMode = SummaryMode.SHORT) -> SummaryRequest:
    return SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW,
                                                start=NOW - timedelta(days=10)), mode, scope)


def channel() -> object:
    return SimpleNamespace(type=discord.ChannelType.text, id=2,
                           guild=SimpleNamespace(id=1), name="합성")


class Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def notice(self, value: str) -> None:
        self.events.append(f"notice:{value}")


def pipeline(recorder: Recorder, outcome: str, *, ready: list[bool] | None = None):
    class Collector:
        async def collect(self, _channel, *, request, **_kwargs):
            recorder.events.append("collect")
            rows = () if outcome == "empty" else (
                MessageRecord(1, 1, 2, 3, "합성", "합성 대화", NOW - timedelta(hours=1)),
            )
            return CollectionOutcome(rows, 0, request.accepted_at, 0, False)

    class Engine:
        async def summarize(self, *_args, **_kwargs):
            recorder.events.append("model")
            if outcome == "model_error":
                raise CodexRunError(CodexFailure.PROCESS)
            if outcome == "usage_limit":
                raise CodexRunError(CodexFailure.USAGE_LIMIT)
            if outcome == "queue_full":
                raise QueueFull
            return SummaryResult("합성 대화를 정리하였소.", "synthetic", 1)

    class Publisher:
        async def publish(self, _request, _result, _messages):
            recorder.events.append("publish")
            return PublicationReceipt((10,), NOW)

    answers = list(ready or [True])

    async def readiness(_guild: int, _channel: int) -> bool:
        recorder.events.append("ready?")
        return answers.pop(0) if len(answers) > 1 else answers[0]

    return Collector(), Engine(), Publisher(), readiness


@pytest.mark.parametrize(
    ("outcome", "tail"),
    [
        ("success", ["collect", "model", "publish"]),
        ("empty", ["collect", f"notice:{EMPTY_NOTICE}"]),
        ("model_error", ["collect", "model", f"notice:{message_for(FailureKind.MODEL)}"]),
        ("usage_limit", ["collect", "model", f"notice:{USAGE_EXHAUSTED_NOTICE}"]),
        ("queue_full", ["collect", "model", f"notice:{QUEUE_FULL_NOTICE}"]),
    ],
)
def test_start_notice_precedes_the_cache_read_and_existing_follow_ups(
    outcome: str, tail: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        recorder = Recorder()
        collector, engine, publisher, readiness = pipeline(recorder, outcome)
        workflow = SummaryWorkflow(collector, engine, publisher, ChannelStates(),  # type: ignore[arg-type]
                                   readiness=readiness)
        await workflow.run(request(), channel(), SimpleNamespace(valid=lambda: True),
                           recorder.notice)  # type: ignore[arg-type]
        assert recorder.events[:2] == ["ready?", f"notice:{START}"]
        assert [event for event in recorder.events[2:] if event != "ready?"] == tail

    asyncio.run(scenario())


def test_lease_change_after_start_notice_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = iter([True, False])
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: next(checks, False))

    async def scenario() -> None:
        recorder = Recorder()
        collector, engine, publisher, readiness = pipeline(recorder, "success")
        workflow = SummaryWorkflow(collector, engine, publisher, ChannelStates(),  # type: ignore[arg-type]
                                   readiness=readiness)
        await workflow.run(request(), channel(), SimpleNamespace(valid=lambda: True),
                           recorder.notice)  # type: ignore[arg-type]
        assert recorder.events[:2] == ["ready?", f"notice:{START}"]
        assert recorder.events[-1] == f"notice:{INVALIDATED_NOTICE}"
        assert "model" not in recorder.events

    asyncio.run(scenario())


def test_lost_readiness_sends_not_ready_without_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        recorder = Recorder()
        collector, engine, publisher, readiness = pipeline(recorder, "success", ready=[False, True])
        states = ChannelStates()
        workflow = SummaryWorkflow(collector, engine, publisher, states,  # type: ignore[arg-type]
                                   readiness=readiness)
        lease = SimpleNamespace(valid=lambda: True)
        await workflow.run(request(), channel(), lease, recorder.notice)  # type: ignore[arg-type]
        assert recorder.events == ["ready?", f"notice:{NOT_READY_NOTICE}"]
        assert await states.active(1, 2) is None
        await workflow.run(request(), channel(), lease, recorder.notice)  # type: ignore[arg-type]
        assert recorder.events[2:4] == ["ready?", f"notice:{START}"]

    asyncio.run(scenario())


def test_failed_start_notice_stops_before_any_read_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        recorder = Recorder()
        collector, engine, publisher, readiness = pipeline(recorder, "success")
        states = ChannelStates()
        workflow = SummaryWorkflow(collector, engine, publisher, states,  # type: ignore[arg-type]
                                   readiness=readiness)
        failures = [discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x")]

        async def flaky(value: str) -> None:
            if failures:
                raise failures.pop()
            await recorder.notice(value)

        lease = SimpleNamespace(valid=lambda: True)
        await workflow.run(request(), channel(), lease, flaky)  # type: ignore[arg-type]
        assert recorder.events == ["ready?"]
        assert await states.active(1, 2) is None
        await workflow.run(request(), channel(), lease, flaky)  # type: ignore[arg-type]
        assert recorder.events[1:3] == ["ready?", f"notice:{START}"]
        assert [event for event in recorder.events[3:] if event != "ready?"] == [
            "collect", "model", "publish",
        ]

    asyncio.run(scenario())


def test_no_start_notice_for_busy_cooldown_or_closing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        recorder = Recorder()
        collector, engine, publisher, readiness = pipeline(recorder, "success")
        states = ChannelStates(SQLiteCooldownStore(tmp_path / "c.db"), clock=lambda: NOW)
        await states.finish_success(1, 2, NOW)
        workflow = SummaryWorkflow(collector, engine, publisher, states,  # type: ignore[arg-type]
                                   readiness=readiness)
        lease = SimpleNamespace(valid=lambda: True)
        await workflow.run(request(), channel(), lease, recorder.notice)  # type: ignore[arg-type]
        assert recorder.events == ["notice:🧊 아직은 때가 아니오. 05분 00초 뒤에 오시오. ⏰"]
        workflow.closing = True
        await workflow.run(request(), channel(), lease, recorder.notice)  # type: ignore[arg-type]
        assert recorder.events[-1] == f"notice:{QUEUE_CLOSED_NOTICE}"
        assert not any(event.endswith("요약해보겠소. ✍️") for event in recorder.events)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("!!요약좀", "📝 1시간 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 3", "📝 3시간 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 30분", "📝 30분 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 10일", START),
        ("!!요약좀 1주", "📝 1주 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 오늘", "📝 오늘 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 100개", "📝 최근 100개 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 오늘 자세히", "📝 오늘 채팅을 자세히 요약해보겠소. ✍️"),
        ("!!요약좀 5시간 짧게 부탁하오", "📝 5시간 채팅을 요약해보겠소. ✍️"),
        ("!!요약좀 5시간 길게 시간순으로", "📝 5시간 채팅을 길게 요약해보겠소. ✍️"),
        ("!!요약좀 10일 <@123>", START),
        ("!!요약좀 자세히 2시간", None),
        ("!!요약좀 31일", None),
    ],
)
def test_gateway_start_notice_uses_only_the_validated_scope(
    content: str, expected: str | None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        recorder = Recorder()
        collector, engine, publisher, readiness = pipeline(recorder, "success")
        workflow = SummaryWorkflow(collector, engine, publisher, ChannelStates(),  # type: ignore[arg-type]
                                   readiness=readiness)
        store = MemoryWatchStore()
        store.replace(1, frozenset({2}))
        client = YoYackClient(
            watch_store=store, settings=Settings.from_environment({"DISCORD_BOT_TOKEN": "x"}),
            clock=lambda: NOW, summary_workflow=workflow,
        )
        sent = AsyncMock()
        target = SimpleNamespace(type=discord.ChannelType.text, id=2,
                                 guild=SimpleNamespace(id=1), name="합성", send=sent)
        event = SimpleNamespace(
            id=500, guild=SimpleNamespace(id=1), channel=target,
            author=SimpleNamespace(bot=False, id=7), webhook_id=None,
            type=discord.MessageType.default, content=content,
        )
        try:
            await client.on_message(event)
        finally:
            await client.close()
        texts = [call.args[0] for call in sent.await_args_list]
        assert all(call.kwargs["allowed_mentions"].to_dict()["parse"] == []
                   for call in sent.await_args_list)
        if expected is None:
            assert not any(text.endswith("요약해보겠소. ✍️") for text in texts)
            assert "collect" not in recorder.events
        else:
            assert texts[0] == expected
            assert recorder.events.index("collect") > 0

    asyncio.run(scenario())


def test_collector_readiness_uses_the_shared_boundary(tmp_path: Path) -> None:
    import sqlite3

    from yoyackbot.backfill import SQLiteBackfillStore
    from yoyackbot.cache_collector import CacheOnlyCollector
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({2}))
    collector = CacheOnlyCollector(watches, SQLiteMessageStore(path), SQLiteBackfillStore(path))
    assert asyncio.run(collector.ready(1, 2)) is False
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE backfill_state SET phase='ready', ready_notice_id=7")
    assert asyncio.run(collector.ready(1, 2)) is True
    assert asyncio.run(collector.ready(1, 3)) is False
