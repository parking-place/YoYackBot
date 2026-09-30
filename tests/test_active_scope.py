"""The first admitted request's scope is kept atomically and always released (T102-P2)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import CollectionOutcome
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryMode,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.parser import OptionKind
from yoyackbot.publisher import PartialPublicationError, PublicationFailure
from yoyackbot.scope import RangeScope
from yoyackbot.state import AdmissionKind, ChannelStates
from yoyackbot.workflow import SummaryWorkflow

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
TEN_DAYS = RangeScope(OptionKind.DAYS, 10)
FIVE_MINUTES = RangeScope(OptionKind.MINUTES, 5)


def test_twenty_same_channel_admissions_see_only_the_first_scope() -> None:
    async def scenario() -> None:
        states = ChannelStates()
        scopes = [TEN_DAYS] + [RangeScope(OptionKind.MINUTES, n) for n in range(1, 20)]
        results = await asyncio.gather(*(
            states.admit(1, 2, scope=scope, mode=SummaryMode.DETAILED if i == 0 else
                         SummaryMode.SHORT)
            for i, scope in enumerate(scopes)
        ))
        accepted = [r for r in results if r.kind is AdmissionKind.ACCEPTED]
        busy = [r for r in results if r.kind is AdmissionKind.BUSY]
        assert len(accepted) == 1 and len(busy) == 19
        assert accepted[0].job is not None and accepted[0].job.scope == TEN_DAYS
        assert all(r.job is accepted[0].job for r in busy)
        assert all(r.job.scope == TEN_DAYS and r.job.mode is SummaryMode.DETAILED
                   for r in busy)

    asyncio.run(scenario())


def test_other_channels_and_guilds_do_not_see_each_other() -> None:
    async def scenario() -> None:
        states = ChannelStates()
        first = await states.admit(1, 2, scope=TEN_DAYS)
        other_channel = await states.admit(1, 3, scope=FIVE_MINUTES)
        other_guild = await states.admit(9, 2, scope=RangeScope(OptionKind.TODAY))
        assert first.kind is other_channel.kind is other_guild.kind is AdmissionKind.ACCEPTED
        assert (await states.admit(1, 3)).job.scope == FIVE_MINUTES
        assert (await states.admit(9, 2)).job.scope == RangeScope(OptionKind.TODAY)
        assert (await states.admit(1, 2)).job.scope == TEN_DAYS

    asyncio.run(scenario())


def test_release_clears_scope_and_wakes_waiters(tmp_path: Path) -> None:
    async def scenario() -> None:
        states = ChannelStates(SQLiteCooldownStore(tmp_path / "c.db"), clock=lambda: NOW)
        job = (await states.admit(1, 2, scope=TEN_DAYS)).job
        assert job is not None and not job.announced.is_set()
        await states.finish(1, 2)
        assert job.announced.is_set() and await states.active(1, 2) is None
        second = (await states.admit(1, 2, scope=FIVE_MINUTES)).job
        await states.finish_success(1, 2, NOW)
        assert second.announced.is_set() and await states.active(1, 2) is None
        assert (await states.admit(1, 2, scope=TEN_DAYS)).kind is AdmissionKind.COOLDOWN
        assert ChannelStates()._active == {}  # a restarted process starts empty

    asyncio.run(scenario())


def request(scope: RangeScope = TEN_DAYS) -> SummaryRequest:
    return SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW,
                                                start=NOW - timedelta(days=10)),
                          SummaryMode.SHORT, scope)


def channel() -> object:
    return SimpleNamespace(type=discord.ChannelType.text, id=2,
                           guild=SimpleNamespace(id=1), name="합성")


def row() -> MessageRecord:
    return MessageRecord(1, 1, 2, 3, "합성", "합성 대화", NOW - timedelta(hours=1))


class Collector:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome

    async def collect(self, _channel, *, request, **_kwargs):
        if self.outcome == "collect_error":
            from yoyackbot.range_collection import CollectionError, CollectionFailure
            raise CollectionError(CollectionFailure.WATCH_CHANGED)
        rows = () if self.outcome == "empty" else (row(),)
        return CollectionOutcome(rows, 0, request.accepted_at, 0, False)


class Engine:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome

    async def summarize(self, *_args, **_kwargs):
        if self.outcome in ("model_error", "usage_limit"):
            kind = CodexFailure.USAGE_LIMIT if self.outcome == "usage_limit" else CodexFailure.PROCESS
            raise CodexRunError(kind)
        if self.outcome == "cancel":
            raise asyncio.CancelledError
        return SummaryResult("합성 대화를 정리하였소.", "synthetic", 1)


class Publisher:
    def __init__(self, outcome: str) -> None:
        self.outcome = outcome

    async def publish(self, request, _result, _messages):
        if self.outcome == "post_error":
            raise PartialPublicationError(
                PublicationFailure.PERMISSION, sent_ids=(), failed_index=0, last_success_at=None,
            )
        return PublicationReceipt((10,), NOW)


@pytest.mark.parametrize(
    "outcome",
    ["success", "empty", "collect_error", "model_error", "usage_limit", "post_error", "cancel",
     "invalidated"],
)
def test_every_exit_releases_the_scope_and_keeps_cooldown_rules(
    outcome: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)
    caplog.set_level("INFO")

    async def scenario() -> None:
        states = ChannelStates(SQLiteCooldownStore(tmp_path / "c.db"), clock=lambda: NOW)
        workflow = SummaryWorkflow(
            Collector(outcome), Engine(outcome), Publisher(outcome), states,  # type: ignore[arg-type]
        )
        valid = outcome != "invalidated"
        lease = SimpleNamespace(valid=lambda: valid)
        notices: list[str] = []

        async def notice(value: str) -> None:
            notices.append(value)

        try:
            await workflow.run(request(), channel(), lease, notice)  # type: ignore[arg-type]
        except asyncio.CancelledError:
            assert outcome == "cancel"
        assert await states.active(1, 2) is None
        after = await states.admit(1, 2, scope=FIVE_MINUTES)
        expected = AdmissionKind.COOLDOWN if outcome == "success" else AdmissionKind.ACCEPTED
        assert after.kind is expected

    asyncio.run(scenario())
    expected_outcome = {
        "success": "success", "empty": "empty", "collect_error": "history_error",
        "model_error": "model_error", "usage_limit": "model_error", "post_error": "post_error",
        "cancel": "cancelled", "invalidated": "channel_unavailable",
    }[outcome]
    assert f'"outcome":"{expected_outcome}"' in caplog.text


def test_shutdown_releases_running_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        started = asyncio.Event()

        class SlowEngine:
            async def summarize(self, *_args, **_kwargs):
                started.set()
                await asyncio.sleep(60)

        states = ChannelStates()
        workflow = SummaryWorkflow(
            Collector("success"), SlowEngine(), Publisher("success"), states,  # type: ignore[arg-type]
        )

        async def notice(_value: str) -> None:
            return None

        task = asyncio.create_task(workflow.run(
            request(), channel(), SimpleNamespace(valid=lambda: True), notice,  # type: ignore[arg-type]
        ))
        await started.wait()
        assert (await states.active(1, 2)).scope == TEN_DAYS
        await workflow.shutdown()
        await asyncio.gather(task, return_exceptions=True)
        assert await states.active(1, 2) is None

    asyncio.run(scenario())
