"""Atomic per-channel admission and the connected summary pipeline."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.collection import EMPTY_NOTICE, CollectionOutcome
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.state import ChannelStates, ChannelStatus
from yoyackbot.workflow import BUSY_NOTICE, SummaryWorkflow

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
