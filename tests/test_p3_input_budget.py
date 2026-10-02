"""B08: cache reads stop at the input budget; the final JSONL bound runs before the model (T120-P3-C)."""

import asyncio
import json
import logging
import math
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.domain import RangeRequest, RequestKind, SummaryRequest, SummaryResult
from yoyackbot.input_files import (
    MIN_MESSAGE_LINE_BYTES,
    ConversationTooLarge,
    serialize_conversation,
)
from yoyackbot.message_store import READ_BATCH_ROWS, SQLiteMessageStore
from yoyackbot.state import ChannelStatus
from yoyackbot.watch_gate import WatchGate
from yoyackbot.watch_store import SQLiteWatchStore
from yoyackbot.workflow import INPUT_TOO_LARGE_NOTICE, build_workflow

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
BODY = "a" * 256


def fill(path, count: int, *, body: str = BODY, channel_id: int = 2) -> None:
    """Bulk insert synthetic rows over the last 20 hours without the per-row writer."""
    SQLiteWatchStore(path)
    start = NOW - timedelta(hours=20)
    step = (20 * 3600 * 1_000_000) // count
    base = int(start.timestamp() * 1_000_000)
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO messages(message_id, guild_id, channel_id, author_id, author_name, "
            "content, created_at_us, edited_at_us, cached_at_us, has_attachment, is_reply) "
            "VALUES (?, 1, ?, ?, '합성 화자', ?, ?, NULL, ?, 0, 0)",
            ((index + 1, channel_id, 3 + index % 4, body, base + index * step, base)
             for index in range(count)),
        )


def store(path) -> SQLiteMessageStore:
    return SQLiteMessageStore(path, clock=lambda: NOW)


@pytest.mark.parametrize("total", [5_000, 50_000])
def test_time_read_stops_within_one_batch_of_the_budget_regardless_of_size(tmp_path, total) -> None:
    path = tmp_path / f"{total}.db"
    fill(path, total)
    budget = 256 * 1_000
    read = []
    with pytest.raises(ConversationTooLarge):
        store(path).recent(1, 2, NOW - timedelta(days=1), NOW, max_bytes=budget, on_rows=read.append)
    assert sum(read) <= math.ceil(budget / 256) + READ_BATCH_ROWS
    assert all(batch <= READ_BATCH_ROWS for batch in read)


def test_small_ranges_read_completely_and_exclude_the_trigger(tmp_path) -> None:
    path = tmp_path / "small.db"
    fill(path, 300)
    read = []
    rows = store(path).recent(
        1, 2, NOW - timedelta(days=1), NOW, exclude_id=7, max_bytes=10_000_000, on_rows=read.append,
    )
    assert len(rows) == 299 and 7 not in {row.message_id for row in rows}
    assert [row.message_id for row in rows] == sorted(row.message_id for row in rows)
    assert read == [128, 128, 43]
    assert len(store(path).recent(1, 2, NOW - timedelta(days=1), NOW)) == 300


def test_tiny_messages_hit_the_serialized_line_floor(tmp_path) -> None:
    path = tmp_path / "tiny.db"
    fill(path, 2_000, body="ㅋ")
    budget = 100 * MIN_MESSAGE_LINE_BYTES
    read = []
    with pytest.raises(ConversationTooLarge):
        store(path).recent(1, 2, NOW - timedelta(days=1), NOW, max_bytes=budget, on_rows=read.append)
    assert sum(read) <= 100 + READ_BATCH_ROWS
    # Exactly at the floor still fits, and the real JSONL is never smaller than the floor.
    rows = store(path).recent(1, 2, NOW - timedelta(days=1), NOW - timedelta(hours=19, minutes=58))
    assert rows
    data = serialize_conversation(rows, channel_name="합성", range_label="합성", trigger_message_id=None,
                                  max_bytes=10_000_000)
    lines = data.decode().splitlines()[1:]
    assert all(len((line + "\n").encode()) >= MIN_MESSAGE_LINE_BYTES for line in lines)


def test_count_read_is_bounded_too(tmp_path) -> None:
    path = tmp_path / "count.db"
    fill(path, 2_000, body="b" * 4_000)
    read = []
    with pytest.raises(ConversationTooLarge):
        store(path).latest(1, 2, NOW - timedelta(days=1), NOW, 1_000, max_bytes=100_000,
                           on_rows=read.append)
    assert sum(read) <= 25 + READ_BATCH_ROWS
    newest = store(path).latest(1, 2, NOW - timedelta(days=1), NOW, 3, max_bytes=100_000)
    assert [row.message_id for row in newest] == [2_000, 1_999, 1_998]


def runtime(tmp_path, monkeypatch, *, max_bytes: int, engine=None):
    path = tmp_path / "cache.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({2}))
    messages = SQLiteMessageStore(path, clock=lambda: NOW)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, "
            "verified_us=?, finished_us=?", (int(NOW.timestamp() * 1_000_000),) * 3,
        )
    channel = SimpleNamespace(
        type=discord.ChannelType.text, id=2, guild=SimpleNamespace(id=1), name="합성 채널",
    )
    channel.send = AsyncMock(return_value=SimpleNamespace(id=500, channel=channel, created_at=NOW))
    client = SimpleNamespace(get_channel=lambda _id: channel, clock=lambda: NOW,
                             cache_available=lambda: True)
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path),
        "YOYACK_MAX_INPUT_BYTES": str(max_bytes),
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "input"),
    })
    if engine is None:
        engine = SimpleNamespace(summarize=AsyncMock(return_value=SummaryResult("합성", "s", 1)))
    else:
        engine = engine(settings)
    monkeypatch.setattr("yoyackbot.workflow.CodexSummaryEngine.from_settings", lambda _: engine)
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda *_: True)
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda *_: True)
    workflow = build_workflow(settings, client, watches, messages)
    _, lease = WatchGate(watches).lease(1, 2)
    return SimpleNamespace(path=path, channel=channel, engine=engine, workflow=workflow,
                           lease=lease, input=tmp_path / "input")


def request(kind=RequestKind.TIME) -> SummaryRequest:
    selected = (RangeRequest(kind, NOW, start=NOW - timedelta(days=1)) if kind is RequestKind.TIME
                else RangeRequest(kind, NOW, count=1_000))
    return SummaryRequest(1, 2, 3, selected)


@pytest.mark.parametrize("kind", [RequestKind.TIME, RequestKind.COUNT])
def test_oversized_range_fails_before_model_publication_and_cooldown(tmp_path, monkeypatch, kind):
    async def scenario():
        context = runtime(tmp_path, monkeypatch, max_bytes=50_000)
        fill(context.path, 3_000)
        notices = AsyncMock()
        await context.workflow.run(request(kind), context.channel, context.lease, notices)
        assert notices.await_args_list[-1].args == (INPUT_TOO_LARGE_NOTICE,)
        context.engine.summarize.assert_not_awaited()
        context.channel.send.assert_not_awaited()
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE
        assert await context.workflow.states.active(1, 2) is None

    asyncio.run(scenario())


def test_final_jsonl_metadata_bound_runs_before_any_workspace_or_model(tmp_path, monkeypatch):
    runner = SimpleNamespace(execute=AsyncMock(return_value="쓰지 않음"))

    async def scenario():
        context = runtime(
            tmp_path, monkeypatch, max_bytes=900,
            engine=lambda settings: CodexSummaryEngine(settings, runner),
        )
        fill(context.path, 3, body="c" * 100)
        rows = context.workflow.collector.messages.recent(1, 2, NOW - timedelta(days=1), NOW)
        # The cache read fits; only the serialized metadata pushes it over the limit.
        assert max(sum(len(r.content) for r in rows), len(rows) * MIN_MESSAGE_LINE_BYTES) <= 900
        assert len(serialize_conversation(rows, channel_name="합성 채널", range_label="x",
                                          trigger_message_id=None, max_bytes=10_000)) > 900
        notices = AsyncMock()
        await context.workflow.run(request(), context.channel, context.lease, notices)
        assert notices.await_args_list[-1].args == (INPUT_TOO_LARGE_NOTICE,)
        runner.execute.assert_not_awaited()
        context.channel.send.assert_not_awaited()
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE
        assert not context.input.exists() or not any(context.input.glob("request-*"))

    asyncio.run(scenario())


def test_input_too_large_metric_is_recorded(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="yoyackbot.metrics")

    async def scenario():
        context = runtime(tmp_path, monkeypatch, max_bytes=50_000)
        fill(context.path, 3_000)
        await context.workflow.run(request(), context.channel, context.lease, AsyncMock())

    asyncio.run(scenario())
    record = json.loads(caplog.records[-1].message)
    assert (record["outcome"], record["failure_detail"], record["model_result"]) == (
        "input_error", "input_size", "not_started",
    )
    assert "aaaa" not in caplog.text
