"""Successful publication cooldown, restart recovery, and failure behavior."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.collection import CollectionOutcome
from yoyackbot.cooldown import SQLiteCooldownStore, cooldown_notice
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.state import AdmissionKind, ChannelStates, ChannelStatus
from yoyackbot.watch_store import SQLiteWatchStore
from yoyackbot.workflow import FAILED_NOTICE, SummaryWorkflow

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def test_300_second_boundary_is_persisted_and_scoped(tmp_path) -> None:
    path = tmp_path / "cooldown.db"
    store = SQLiteCooldownStore(path)
    store.record_success(1, 2, NOW)
    assert store.remaining(1, 2, NOW) == 300
    assert store.remaining(1, 2, NOW + timedelta(seconds=95)) == 205
    assert cooldown_notice(205) == "🧊 아직은 때가 아니오. 03분 25초 뒤에 오시오. ⏰"
    assert store.remaining(1, 2, NOW + timedelta(seconds=299)) == 1
    assert store.remaining(1, 2, NOW + timedelta(seconds=300)) == 0
    assert store.remaining(1, 2, NOW + timedelta(days=1)) == 0
    assert store.remaining(1, 3, NOW) == 0
    assert store.remaining(2, 2, NOW) == 0
    assert SQLiteCooldownStore(path).remaining(1, 2, NOW + timedelta(seconds=95)) == 205


def test_restarted_state_uses_remaining_time_and_clock_change_cannot_extend_it(tmp_path) -> None:
    path = tmp_path / "cooldown.db"
    store = SQLiteCooldownStore(path)
    store.record_success(1, 2, NOW)
    wall = [NOW + timedelta(seconds=95)]
    ticks = [100.0]

    async def scenario() -> None:
        states = ChannelStates(store, clock=lambda: wall[0], monotonic=lambda: ticks[0])
        admission = await states.admit(1, 2)
        assert (admission.kind, admission.remaining_seconds) == (AdmissionKind.COOLDOWN, 205)
        wall[0] -= timedelta(hours=1)
        ticks[0] += 204
        assert (await states.admit(1, 2)).remaining_seconds == 1
        ticks[0] += 1
        assert (await states.admit(1, 2)).kind is AdmissionKind.ACCEPTED
        await states.finish(1, 2)
        assert await states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


def test_success_is_stored_only_after_publication_and_failure_can_retry(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)
    path = tmp_path / "cooldown.db"
    store = SQLiteCooldownStore(path)
    states = ChannelStates(store, clock=lambda: NOW, monotonic=lambda: 100.0)
    record = MessageRecord(1, 1, 2, 3, "가람", "합성", NOW - timedelta(minutes=1))
    request = SummaryRequest(
        1, 2, 3, RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(minutes=5))
    )
    channel = SimpleNamespace(
        type=discord.ChannelType.text, id=2, guild=SimpleNamespace(id=1), name="합성"
    )
    lease = SimpleNamespace(valid=lambda: True)

    class Collector:
        calls = 0

        async def collect(self, *_args, **_kwargs):
            self.calls += 1
            return CollectionOutcome((record,), 0, NOW, 0, False)

    class Engine:
        calls = 0

        async def summarize(self, *_args, **_kwargs):
            self.calls += 1
            return SummaryResult("가람이 합성 대화를 했소.", "fake", 1)

    class Publisher:
        calls = 0

        async def publish(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("synthetic publication failure")
            return PublicationReceipt((100,), NOW)

    collector, engine, publisher = Collector(), Engine(), Publisher()
    workflow = SummaryWorkflow(collector, engine, publisher, states)  # type: ignore[arg-type]

    async def scenario() -> None:
        notices: list[str] = []

        async def notice(value: str) -> None:
            notices.append(value)

        await workflow.run(request, channel, lease, notice)  # type: ignore[arg-type]
        assert notices == [FAILED_NOTICE]
        assert store.remaining(1, 2, NOW) == 0
        assert await states.status(1, 2) is ChannelStatus.IDLE

        await workflow.run(request, channel, lease, notice)  # type: ignore[arg-type]
        assert collector.calls == engine.calls == publisher.calls == 2
        assert store.remaining(1, 2, NOW) == 300
        assert await states.status(1, 2) is ChannelStatus.COOLDOWN

        await workflow.run(request, channel, lease, notice)  # type: ignore[arg-type]
        assert notices[-1] == "🧊 아직은 때가 아니오. 05분 00초 뒤에 오시오. ⏰"
        assert collector.calls == engine.calls == publisher.calls == 2

    asyncio.run(scenario())


def test_watch_removal_clears_cooldown_and_schema_four_migrates_without_loss(tmp_path) -> None:
    path = tmp_path / "cooldown.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({2, 3}))
    watches.replace(2, frozenset({2}))
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE summary_cooldowns")
        connection.execute("PRAGMA user_version=4")
    store = SQLiteCooldownStore(path)
    assert SQLiteWatchStore(path).get(1) == frozenset({2, 3})
    store.record_success(1, 2, NOW)
    store.record_success(2, 2, NOW)
    watches.remove_channel(1, 2)
    assert store.remaining(1, 2, NOW) == 0
    assert store.remaining(2, 2, NOW) == 300
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
