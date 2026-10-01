"""Duplicate requests hear the running job's range, after its start notice (T102-P4)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

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
from yoyackbot.job_queue import SummaryJobQueue
from yoyackbot.parser import OptionKind
from yoyackbot.scope import RangeScope
from yoyackbot.state import ChannelStates
from yoyackbot.workflow import SummaryWorkflow

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
TEN_DAYS = RangeScope(OptionKind.DAYS, 10)
FIVE_MINUTES = RangeScope(OptionKind.MINUTES, 5)
START = "📝 10일 채팅을 요약해보겠소. ✍️"
BUSY = "⏳ 현재 10일 분 채팅을 요약중이오. 🔄\n🧘 참을성을 가져보시오. 🙏"


def request(scope: RangeScope, mode: SummaryMode = SummaryMode.SHORT,
            channel_id: int = 2, guild_id: int = 1) -> SummaryRequest:
    return SummaryRequest(guild_id, channel_id, 3,
                          RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(minutes=5)),
                          mode, scope)


def channel(channel_id: int = 2, guild_id: int = 1) -> object:
    return SimpleNamespace(type=discord.ChannelType.text, id=channel_id,
                           guild=SimpleNamespace(id=guild_id), name="합성")


class Gates:
    """Hold the first job at a chosen stage so duplicates arrive while it is there."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.counts = {"collect": 0, "model": 0, "publish": 0}

    async def at(self, stage: str) -> None:
        if stage == self.stage:
            self.reached.set()
            await self.release.wait()


def pipeline(gates: Gates):
    class Collector:
        async def collect(self, _channel, *, guild_id, channel_id, request, **_kwargs):
            gates.counts["collect"] += 1
            await gates.at("collect")
            return CollectionOutcome(
                (MessageRecord(1, guild_id, channel_id, 3, "합성", "합성 대화",
                               NOW - timedelta(minutes=1)),),
                0, request.accepted_at, 0, False,
            )

    class Engine:
        async def summarize(self, *_args, **_kwargs):
            gates.counts["model"] += 1
            await gates.at("model")
            return SummaryResult("합성 대화를 정리하였소.", "synthetic", 1)

    class Publisher:
        async def publish(self, request, _result, _messages):
            gates.counts["publish"] += 1
            await gates.at("publish")
            return PublicationReceipt((10,), NOW)

    async def ready(_guild: int, _channel: int) -> bool:
        return True

    return Collector(), Engine(), Publisher(), ready


@pytest.mark.parametrize("stage", ["start", "collect", "queue", "model", "publish"])
def test_duplicates_hear_the_first_range_at_every_stage(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        gates = Gates(stage)
        collector, engine, publisher, ready = pipeline(gates)
        queue = SummaryJobQueue(concurrency=1, capacity=4, wait_seconds=5)
        states = ChannelStates(SQLiteCooldownStore(tmp_path / "c.db"), clock=lambda: NOW)
        workflow = SummaryWorkflow(collector, engine, publisher, states, queue,  # type: ignore[arg-type]
                                   readiness=ready)
        sent: list[tuple[int, str]] = []
        blocker = None
        if stage == "queue":
            blocker = await queue.acquire()

        def notice_for(channel_id: int):
            async def notice(value: str) -> None:
                if stage == "start" and value == START:
                    gates.reached.set()
                    await gates.release.wait()
                sent.append((channel_id, value))
            return notice

        lease = SimpleNamespace(valid=lambda: True)
        first = asyncio.create_task(workflow.run(
            request(TEN_DAYS), channel(), lease, notice_for(2)))  # type: ignore[arg-type]
        if stage == "queue":
            while not sent:
                await asyncio.sleep(0)
        else:
            await gates.reached.wait()
        duplicates = [
            asyncio.create_task(workflow.run(
                request(FIVE_MINUTES, SummaryMode.SHORT), channel(), lease,
                notice_for(2)))  # type: ignore[arg-type]
            for _ in range(19)
        ]
        other = asyncio.create_task(workflow.run(
            request(FIVE_MINUTES, channel_id=7, guild_id=9), channel(7, 9), lease,
            notice_for(7)))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        if stage == "queue":
            assert blocker is not None
            await blocker.__aexit__(None, None, None)
        gates.release.set()
        await asyncio.gather(first, *duplicates, other)

        same = [value for channel_id, value in sent if channel_id == 2]
        assert same[0] == START
        assert same.count(BUSY) == 19 and same.count(START) == 1
        assert not any("5분" in value for value in same)
        assert [value for channel_id, value in sent if channel_id == 7] == [
            "📝 5분 채팅을 요약해보겠소. ✍️"
        ]
        assert gates.counts == {"collect": 2, "model": 2, "publish": 2}
        assert (await states.admit(1, 2)).kind.value == "cooldown"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("mode", "busy"),
    [
        (SummaryMode.DETAILED, "⏳ 현재 10일 분 채팅을 자세히 요약중이오. 🔄\n🧘 참을성을 가져보시오. 🙏"),
        (SummaryMode.LONG, "⏳ 현재 10일 분 채팅을 길게 요약중이오. 🔄\n🧘 참을성을 가져보시오. 🙏"),
    ],
)
def test_busy_notice_keeps_the_running_mode(
    mode: SummaryMode, busy: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        gates = Gates("model")
        collector, engine, publisher, ready = pipeline(gates)
        workflow = SummaryWorkflow(collector, engine, publisher, ChannelStates(),  # type: ignore[arg-type]
                                   readiness=ready)
        sent: list[str] = []

        async def notice(value: str) -> None:
            sent.append(value)

        lease = SimpleNamespace(valid=lambda: True)
        first = asyncio.create_task(workflow.run(request(TEN_DAYS, mode), channel(), lease, notice))  # type: ignore[arg-type]
        await gates.reached.wait()
        await workflow.run(request(FIVE_MINUTES), channel(), lease, notice)  # type: ignore[arg-type]
        gates.release.set()
        await first
        assert sent[1] == busy

    asyncio.run(scenario())


def test_failed_start_notice_lets_the_waiter_run_its_own_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        gates = Gates("never")
        collector, engine, publisher, ready = pipeline(gates)
        states = ChannelStates()
        workflow = SummaryWorkflow(collector, engine, publisher, states,  # type: ignore[arg-type]
                                   readiness=ready)
        sending = asyncio.Event()
        fail = asyncio.Event()
        sent: list[str] = []

        async def first_notice(value: str) -> None:
            sending.set()
            await fail.wait()
            raise discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x")

        async def second_notice(value: str) -> None:
            sent.append(value)

        lease = SimpleNamespace(valid=lambda: True)
        first = asyncio.create_task(workflow.run(
            request(TEN_DAYS), channel(), lease, first_notice))  # type: ignore[arg-type]
        await sending.wait()
        second = asyncio.create_task(workflow.run(
            request(FIVE_MINUTES), channel(), lease, second_notice))  # type: ignore[arg-type]
        await asyncio.sleep(0.01)
        assert sent == []
        fail.set()
        await asyncio.gather(first, second)
        assert sent == ["📝 5분 채팅을 요약해보겠소. ✍️"]
        assert gates.counts == {"collect": 1, "model": 1, "publish": 1}
        assert await states.active(1, 2) is None

    asyncio.run(scenario())


def test_finished_job_leaves_no_ghost_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        gates = Gates("never")
        collector, engine, publisher, ready = pipeline(gates)
        clock = [NOW]
        states = ChannelStates(SQLiteCooldownStore(tmp_path / "c.db"), clock=lambda: clock[0],
                               monotonic=lambda: (clock[0] - NOW).total_seconds())
        workflow = SummaryWorkflow(collector, engine, publisher, states,  # type: ignore[arg-type]
                                   readiness=ready)
        sent: list[str] = []

        async def notice(value: str) -> None:
            sent.append(value)

        lease = SimpleNamespace(valid=lambda: True)
        await workflow.run(request(TEN_DAYS), channel(), lease, notice)  # type: ignore[arg-type]
        await workflow.run(request(FIVE_MINUTES), channel(), lease, notice)  # type: ignore[arg-type]
        assert sent == [START, "🧊 아직은 때가 아니오. 05분 00초 뒤에 오시오. ⏰"]
        clock[0] = NOW + timedelta(minutes=5, seconds=1)
        await workflow.run(request(FIVE_MINUTES), channel(), lease, notice)  # type: ignore[arg-type]
        assert sent[-1] == "📝 5분 채팅을 요약해보겠소. ✍️"
        assert not any("현재" in value for value in sent)

    asyncio.run(scenario())
