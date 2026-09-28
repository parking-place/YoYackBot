"""Atomic per-channel admission and the connected summary pipeline."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import EMPTY_NOTICE, CollectionOutcome
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.publisher import PartialPublicationError, PublicationFailure
from yoyackbot.state import ChannelStates, ChannelStatus
from yoyackbot.workflow import BUSY_NOTICE, INVALIDATED_NOTICE, SummaryWorkflow

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
RECORD = MessageRecord(1, 1, 2, 3, "가람", "합성 대화", NOW - timedelta(minutes=1))


def request(guild_id: int = 1, channel_id: int = 2) -> SummaryRequest:
    return SummaryRequest(guild_id, channel_id, 3,
                          RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(minutes=5)))


def channel(guild_id: int = 1, channel_id: int = 2) -> object:
    return SimpleNamespace(type=discord.ChannelType.text, id=channel_id,
                           guild=SimpleNamespace(id=guild_id), name="합성")


def test_twenty_same_channel_requests_run_pipeline_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        all_busy = asyncio.Event()
        notices: list[str] = []

        class Collector:
            calls = 0

            async def collect(self, *_args: object, **_kwargs: object) -> CollectionOutcome:
                self.calls += 1
                entered.set()
                await release.wait()
                return CollectionOutcome((RECORD,), 0, NOW, 0, False)

        class Engine:
            calls = 0

            async def summarize(self, *_args: object, **_kwargs: object) -> SummaryResult:
                self.calls += 1
                return SummaryResult("가람이 합성 대화를 했소.", "fake", 1)

        class Publisher:
            calls = 0

            async def publish(self, *_args: object, **_kwargs: object) -> PublicationReceipt:
                self.calls += 1
                return PublicationReceipt((100,), NOW)

        collector, engine, publisher = Collector(), Engine(), Publisher()
        workflow = SummaryWorkflow(collector, engine, publisher)  # type: ignore[arg-type]
        lease = SimpleNamespace(valid=lambda: True)

        async def notice(text: str) -> None:
            notices.append(text)
            if len(notices) == 19:
                all_busy.set()

        jobs = [asyncio.create_task(workflow.run(
            request(), channel(), lease, notice  # type: ignore[arg-type]
        )) for _ in range(20)]
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.wait_for(all_busy.wait(), 5)
        assert await workflow.states.status(1, 2) is ChannelStatus.SUMMARIZING
        release.set()
        await asyncio.gather(*jobs)
        assert collector.calls == engine.calls == publisher.calls == 1
        assert notices == [BUSY_NOTICE] * 19
        assert await workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


def test_different_guild_and_channel_states_are_independent() -> None:
    async def scenario() -> None:
        states = ChannelStates()
        assert await states.begin(1, 2)
        assert not await states.begin(1, 2)
        assert await states.begin(1, 3)
        assert await states.begin(2, 2)
        assert await states.status(1, 2) is ChannelStatus.SUMMARIZING
        await states.finish(1, 2)
        assert await states.status(1, 2) is ChannelStatus.IDLE
        assert await states.status(1, 3) is ChannelStatus.SUMMARIZING
        assert await states.status(2, 2) is ChannelStatus.SUMMARIZING

    asyncio.run(scenario())


def test_empty_result_never_calls_model_or_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    class EmptyCollector:
        async def collect(self, *_args: object, **_kwargs: object) -> CollectionOutcome:
            return CollectionOutcome((), 0, NOW, 0, False)

    class Unused:
        async def summarize(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("Model must not run on empty input")

        async def publish(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("Publisher must not run on empty input")

    async def scenario() -> None:
        notices: list[str] = []

        async def notice(text: str) -> None:
            notices.append(text)

        unused = Unused()
        workflow = SummaryWorkflow(EmptyCollector(), unused, unused)  # type: ignore[arg-type]
        await workflow.run(
            request(), channel(), SimpleNamespace(valid=lambda: True), notice  # type: ignore[arg-type]
        )
        assert notices == [EMPTY_NOTICE]
        assert await workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["collection", "model", "publication"])
def test_failure_releases_channel_and_allows_retry_without_success_cooldown(
    tmp_path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)
    fail = [True]

    class Collector:
        async def collect(self, *_args, **_kwargs):
            if fail[0] and failure == "collection":
                raise OSError("synthetic cache failure")
            return CollectionOutcome((RECORD,), 0, NOW, 0, False)

    class Engine:
        async def summarize(self, *_args, **_kwargs):
            if fail[0] and failure == "model":
                raise CodexRunError(CodexFailure.PROCESS)
            return SummaryResult("가람이 합성 대화를 했소.", "fake", 1)

    class Publisher:
        async def publish(self, *_args, **_kwargs):
            if fail[0] and failure == "publication":
                raise PartialPublicationError(
                    PublicationFailure.UNCERTAIN, sent_ids=(99,),
                    failed_index=2, last_success_at=NOW,
                )
            return PublicationReceipt((100,), NOW)

    async def scenario() -> None:
        notices: list[str] = []

        async def notice(value: str) -> None:
            notices.append(value)

        store = SQLiteCooldownStore(tmp_path / "state.db")
        states = ChannelStates(store, clock=lambda: NOW)
        workflow = SummaryWorkflow(Collector(), Engine(), Publisher(), states)  # type: ignore[arg-type]
        lease = SimpleNamespace(valid=lambda: True)
        await workflow.run(request(), channel(), lease, notice)  # type: ignore[arg-type]
        expected = {
            "collection": "요약을 마치지 못했소. 잠시 후 다시 시도하시오.",
            "model": message_for(FailureKind.MODEL),
            "publication": message_for(FailureKind.SEND),
        }[failure]
        assert notices == [expected]
        assert store.remaining(1, 2, NOW) == 0
        assert await states.status(1, 2) is ChannelStatus.IDLE
        fail[0] = False
        await workflow.run(request(), channel(), lease, notice)  # type: ignore[arg-type]
        assert await states.status(1, 2) is ChannelStatus.COOLDOWN

    asyncio.run(scenario())


def test_watch_removed_after_collection_prevents_model_and_releases_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)
    watched = [True]

    class Collector:
        async def collect(self, *_args, **_kwargs):
            watched[0] = False
            return CollectionOutcome((RECORD,), 0, NOW, 0, False)

    class Unused:
        async def summarize(self, *_args, **_kwargs):
            raise AssertionError("Model must not run after watch removal")

        async def publish(self, *_args, **_kwargs):
            raise AssertionError("Publisher must not run after watch removal")

    async def scenario() -> None:
        notices: list[str] = []

        async def notice(value: str) -> None:
            notices.append(value)

        store = SQLiteCooldownStore(tmp_path / "state.db")
        states = ChannelStates(store, clock=lambda: NOW)
        unused = Unused()
        workflow = SummaryWorkflow(Collector(), unused, unused, states)  # type: ignore[arg-type]
        await workflow.run(
            request(), channel(), SimpleNamespace(valid=lambda: watched[0]), notice  # type: ignore[arg-type]
        )
        assert notices == [INVALIDATED_NOTICE]
        assert await states.status(1, 2) is ChannelStatus.IDLE
        assert store.remaining(1, 2, NOW) == 0

    asyncio.run(scenario())


def test_permission_loss_during_model_cancels_it_before_publication(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed = [True]
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: allowed[0])

    class Collector:
        async def collect(self, *_args, **_kwargs):
            return CollectionOutcome((RECORD,), 0, NOW, 0, False)

    class Engine:
        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def summarize(self, *_args, **_kwargs):
            self.entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    class Publisher:
        async def publish(self, *_args, **_kwargs):
            raise AssertionError("Publisher must not run after permission loss")

    async def scenario() -> None:
        notices: list[str] = []

        async def notice(value: str) -> None:
            notices.append(value)

        engine = Engine()
        store = SQLiteCooldownStore(tmp_path / "state.db")
        states = ChannelStates(store, clock=lambda: NOW)
        workflow = SummaryWorkflow(Collector(), engine, Publisher(), states)  # type: ignore[arg-type]
        task = asyncio.create_task(workflow.run(
            request(), channel(), SimpleNamespace(valid=lambda: True), notice  # type: ignore[arg-type]
        ))
        await asyncio.wait_for(engine.entered.wait(), 2)
        allowed[0] = False
        await asyncio.wait_for(task, 2)
        assert engine.cancelled.is_set()
        assert notices == [INVALIDATED_NOTICE]
        assert await states.status(1, 2) is ChannelStatus.IDLE
        assert store.remaining(1, 2, NOW) == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("blocked_stage", ["collection", "model", "publication"])
def test_external_cancellation_releases_state_at_each_await_point(
    tmp_path, monkeypatch: pytest.MonkeyPatch, blocked_stage: str,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        entered = asyncio.Event()
        block = [True]

        async def maybe_block(stage: str) -> None:
            if block[0] and stage == blocked_stage:
                entered.set()
                await asyncio.Event().wait()

        class Collector:
            async def collect(self, *_args, **_kwargs):
                await maybe_block("collection")
                return CollectionOutcome((RECORD,), 0, NOW, 0, False)

        class Engine:
            async def summarize(self, *_args, **_kwargs):
                await maybe_block("model")
                return SummaryResult("가람이 합성 대화를 했소.", "fake", 1)

        class Publisher:
            async def publish(self, *_args, **_kwargs):
                await maybe_block("publication")
                return PublicationReceipt((100,), NOW)

        async def notice(_value: str) -> None:
            pass

        store = SQLiteCooldownStore(tmp_path / "state.db")
        states = ChannelStates(store, clock=lambda: NOW)
        workflow = SummaryWorkflow(Collector(), Engine(), Publisher(), states)  # type: ignore[arg-type]
        lease = SimpleNamespace(valid=lambda: True)
        task = asyncio.create_task(workflow.run(
            request(), channel(), lease, notice  # type: ignore[arg-type]
        ))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert await states.status(1, 2) is ChannelStatus.IDLE
        assert store.remaining(1, 2, NOW) == 0
        block[0] = False
        await workflow.run(request(), channel(), lease, notice)  # type: ignore[arg-type]
        assert await states.status(1, 2) is ChannelStatus.COOLDOWN

    asyncio.run(scenario())
