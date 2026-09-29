"""Synthetic, content-free concurrent summary baseline; run on a test LXC only."""

import asyncio
import json
import logging
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord

import yoyackbot.workflow as workflow_module
from yoyackbot.collection import CollectionOutcome
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.job_queue import SummaryJobQueue
from yoyackbot.state import ChannelStates
from yoyackbot.workflow import SummaryWorkflow


class MetricCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.rows.append(json.loads(record.getMessage()))


class Collector:
    async def collect(self, _channel: object, *, guild_id: int, channel_id: int,
                      request: RangeRequest, **_kwargs: object) -> CollectionOutcome:
        await asyncio.sleep(0.003)
        count = request.count or 1
        records = tuple(MessageRecord(
            channel_id * 1000 + index, guild_id, channel_id, index + 1,
            "합성 화자", "합성 내용", request.accepted_at - timedelta(seconds=index + 1),
        ) for index in range(count))
        return CollectionOutcome(records, 0, request.accepted_at, 0, False, count, 0)


class Engine:
    async def summarize(self, messages: tuple[MessageRecord, ...], **_kwargs: object) -> SummaryResult:
        await asyncio.sleep(0.11 if len(messages) > 100 else 0.015)
        return SummaryResult("합성 요약", "synthetic", len(messages))


class Publisher:
    def __init__(self) -> None:
        self.published: list[tuple[int, int]] = []
        self.timings_ms: list[int] = []

    async def publish(self, request: SummaryRequest, _result: SummaryResult,
                      messages: tuple[MessageRecord, ...]) -> PublicationReceipt:
        assert all((message.guild_id, message.channel_id) == (
            request.guild_id, request.channel_id
        ) for message in messages), "cross-channel message leak"
        started = time.monotonic()
        await asyncio.sleep(0.003)
        self.timings_ms.append(round((time.monotonic() - started) * 1000))
        self.published.append((request.guild_id, request.channel_id))
        return PublicationReceipt((request.channel_id * 1000,), datetime.now(UTC))


def percentile95(values: list[int]) -> int:
    return sorted(values)[max(0, (len(values) * 95 + 99) // 100 - 1)] if values else 0


async def scenario(count: int, *, mixed_guilds: bool) -> dict:
    now = datetime.now(UTC)
    capture = MetricCapture()
    logger = logging.getLogger("yoyackbot.metrics")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        with tempfile.TemporaryDirectory() as temporary:
            publisher = Publisher()
            workflow = SummaryWorkflow(
                Collector(), Engine(), publisher,
                ChannelStates(SQLiteCooldownStore(Path(temporary) / "state.db")),
                SummaryJobQueue(concurrency=1, capacity=4, wait_seconds=0.08),
            )
            channels = [(
                (1 if not mixed_guilds or index % 2 == 0 else 2), 10 + index
            ) for index in range(count)]
            notices: list[str] = []

            async def notice(value: str) -> None:
                notices.append(value)

            def job(guild_id: int, channel_id: int, size: int) -> asyncio.Task:
                request = SummaryRequest(guild_id, channel_id, 3, RangeRequest(
                    RequestKind.COUNT, now, count=size,
                ))
                channel = SimpleNamespace(
                    type=discord.ChannelType.text, id=channel_id,
                    guild=SimpleNamespace(id=guild_id), name="합성 채널",
                )
                lease = SimpleNamespace(valid=lambda: True)
                return asyncio.create_task(workflow.run(request, channel, lease, notice))

            jobs = [job(guild_id, channel_id, 120 if index % 2 == 0 else 8)
                    for index, (guild_id, channel_id) in enumerate(channels)]
            await asyncio.sleep(0.01)
            duplicate = job(*channels[0], 8)
            await asyncio.gather(*jobs, duplicate)
            if publisher.published:
                await job(*publisher.published[0], 8)
            rows = capture.rows
            outcomes = Counter(row["outcome"] for row in rows)
            assert outcomes["busy"] == 1, outcomes
            assert len(publisher.published) == outcomes["success"]
            assert len(set(publisher.published)) == len(publisher.published)
            assert all(row["history_pages"] == 0 for row in rows)
            assert outcomes["cooldown"] == 1, outcomes
            success = [row for row in rows if row["outcome"] == "success"]
            return {
                "channels": count,
                "guild_layout": "mixed" if mixed_guilds else "same",
                "outcomes": dict(sorted(outcomes.items())),
                "collection_p95_ms": percentile95([row["collection_ms"] for row in success]),
                "queue_p95_ms": percentile95([row["queue_ms"] for row in success]),
                "model_p95_ms": percentile95([row["model_ms"] for row in success]),
                "post_p95_ms": percentile95(publisher.timings_ms),
                "duration_p95_ms": percentile95([row["duration_ms"] for row in success]),
                "max_queue_ms": max((row["queue_ms"] for row in rows), default=0),
                "published": len(publisher.published),
                "separated": True,
            }
    finally:
        logger.removeHandler(capture)


async def main() -> None:
    workflow_module.valid_channel = lambda _guild, _channel_id: True
    for mixed in (False, True):
        for count in (2, 4, 8):
            print(json.dumps(await scenario(count, mixed_guilds=mixed), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
