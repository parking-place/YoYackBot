"""Current workflow consumes pending verification and retains its generation until publication."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.backfill import NOT_READY_NOTICE, BackfillError, InitialBackfill
from yoyackbot.cache_collector import BackfillNotReady, CacheCollectionOutcome
from yoyackbot.collection import CollectionUnavailable
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryRequest, SummaryResult
from yoyackbot.job_queue import SummaryJobQueue
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.state import ChannelStatus
from yoyackbot.watch_gate import WatchGate
from yoyackbot.watch_store import SQLiteWatchStore
from yoyackbot.workflow import build_workflow

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def runtime(tmp_path, monkeypatch, *, retention_days=30):
    path = tmp_path / "cache.db"
    clock = SimpleNamespace(now=NOW, available=True)
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({2}))
    messages = SQLiteMessageStore(path, retention_days=retention_days, clock=lambda: clock.now)
    # This fixture starts at an already-verified state; backfill integration has its
    # own page/reconnect tests. All summary calls still use the real runtime builder.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, "
            "verified_us=?, finished_us=?",
            (int(NOW.timestamp() * 1_000_000),) * 3,
        )
    channel = SimpleNamespace(
        type=discord.ChannelType.text, id=2, guild=SimpleNamespace(id=1), name="합성 채널",
    )
    channel.send = AsyncMock(return_value=SimpleNamespace(id=500, channel=channel, created_at=NOW))
    client = SimpleNamespace(
        get_channel=lambda channel_id: channel if channel_id == 2 else None,
        clock=lambda: clock.now, cache_available=lambda: clock.available,
    )
    engine = SimpleNamespace(summarize=AsyncMock(return_value=SummaryResult(
        "합성 대화를 정리했소.", "synthetic", 1,
    )))
    monkeypatch.setattr("yoyackbot.workflow.CodexSummaryEngine.from_settings", lambda _: engine)
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda *_: True)
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda *_: True)
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path),
        "YOYACK_CACHE_RETENTION_DAYS": str(retention_days),
    })
    workflow = build_workflow(settings, client, watches, messages)
    _, lease = WatchGate(watches).lease(1, 2)
    assert lease is not None
    return SimpleNamespace(
        path=path, clock=clock, watches=watches, messages=messages, channel=channel,
        engine=engine, workflow=workflow, lease=lease,
    )


def row(message_id=100, *, created_at=None):
    return MessageRecord(message_id, 1, 2, 3, "합성 화자", "합성 대화", created_at or NOW - timedelta(hours=1))


def request(*, kind=RequestKind.TIME, days=1, count=3):
    selected = (
        RangeRequest(kind, NOW, start=NOW - timedelta(days=days))
        if kind is RequestKind.TIME else RangeRequest(kind, NOW, count=count)
    )
    return SummaryRequest(1, 2, 3, selected)


def pending(context):
    context.messages.mark_all_watched_recheck(
        NOW - timedelta(hours=2), NOW, reason="synthetic_reconnect",
    )


def completed_new_generation(context):
    # A reconnect and a fast repair can both finish between the model's polling ticks.
    with sqlite3.connect(context.path) as connection:
        connection.execute("UPDATE backfill_state SET started_us=started_us+1")


async def collect(context, selected=None):
    return await context.workflow.collector.collect(
        context.channel, guild_id=1, channel_id=2,
        request=(selected or request()).requested_range,
    )


def test_build_workflow_rejects_pending_even_when_phase_is_ready(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)
        assert await context.workflow.collector.ready(1, 2)
        pending(context)
        assert not await context.workflow.collector.ready(1, 2)
        with pytest.raises(BackfillNotReady):
            await collect(context)
        notices = AsyncMock()
        await context.workflow.run(request(), context.channel, context.lease, notices)
        notices.assert_awaited_once_with(NOT_READY_NOTICE)
        context.engine.summarize.assert_not_awaited()
        context.channel.send.assert_not_awaited()
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


def test_repaired_offline_edit_and_delete_reach_the_actual_runtime_engine(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        edited_at = NOW - timedelta(hours=2)
        deleted_at = NOW - timedelta(hours=3)
        edited_id = discord.utils.time_snowflake(edited_at) + 1
        deleted_id = discord.utils.time_snowflake(deleted_at) + 2
        context.messages.upsert(MessageRecord(
            edited_id, 1, 2, 3, "합성 화자", "수정 전 합성 대화", edited_at,
        ), cached_at=NOW)
        context.messages.upsert(MessageRecord(
            deleted_id, 1, 2, 3, "합성 화자", "오프라인에서 삭제한 합성 대화", deleted_at,
        ), cached_at=NOW)
        edited_message = SimpleNamespace(
            id=edited_id, channel=context.channel, guild=context.channel.guild,
            author=SimpleNamespace(id=3, bot=False, display_name="합성 화자"),
            webhook_id=None, type=discord.MessageType.default, attachments=(),
            content="수정 후 합성 대화", created_at=edited_at,
            edited_at=NOW - timedelta(minutes=5),
        )

        class Source:
            calls = 0

            async def fetch_page(self, _channel, *, before, limit, after=None):
                self.calls += 1
                return [message for message in (edited_message,)
                        if (after or 0) < message.id < before][:limit]

        backfills = context.workflow.collector.backfills
        backfills.schedule_ready_recheck(start=NOW - timedelta(minutes=10), end=NOW)
        assert not await context.workflow.collector.ready(1, 2)
        source = Source()
        worker = InitialBackfill(backfills, source, clock=lambda: context.clock.now)
        for _ in range(4):
            state = backfills.get(1, 2)
            assert state is not None
            if state.ready:
                break
            assert await worker.step(context.channel, state)
        assert await context.workflow.collector.ready(1, 2)
        history_calls = source.calls
        assert history_calls > 0
        await context.workflow.run(request(), context.channel, context.lease, AsyncMock())
        context.engine.summarize.assert_awaited_once()
        selected = context.engine.summarize.await_args.args[0]
        assert [(message.message_id, message.content) for message in selected] == [
            (edited_id, "수정 후 합성 대화"),
        ]
        context.channel.send.assert_awaited_once()
        assert source.calls == history_calls

    asyncio.run(scenario())


def test_gateway_pending_persistence_failure_blocks_the_built_workflow(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)
        context.clock.available = False
        notices = AsyncMock()
        await context.workflow.run(request(), context.channel, context.lease, notices)
        notices.assert_awaited_once_with(NOT_READY_NOTICE)
        context.engine.summarize.assert_not_awaited()
        context.channel.send.assert_not_awaited()

    asyncio.run(scenario())


def test_ready_ignores_only_expired_and_other_channel_recheck_ranges(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch, retention_days=1)
        cutoff = NOW - timedelta(days=1)
        with sqlite3.connect(context.path) as connection:
            connection.executemany(
                "INSERT INTO coverage_recheck(guild_id, channel_id, start_us, end_us, reason) "
                "VALUES (?, ?, ?, ?, 'synthetic')",
                [
                    (1, 2, int((cutoff - timedelta(hours=1)).timestamp() * 1_000_000),
                     int(cutoff.timestamp() * 1_000_000)),
                    (2, 2, int((NOW - timedelta(hours=1)).timestamp() * 1_000_000),
                     int(NOW.timestamp() * 1_000_000)),
                ],
            )
        assert await context.workflow.collector.ready(1, 2)
        with sqlite3.connect(context.path) as connection:
            connection.execute(
                "UPDATE coverage_recheck SET end_us=end_us+1 WHERE guild_id=1 AND channel_id=2"
            )
        assert not await context.workflow.collector.ready(1, 2)

    asyncio.run(scenario())


def test_phase_ready_still_requires_the_first_watch_notice(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        with sqlite3.connect(context.path) as connection:
            connection.execute("UPDATE backfill_state SET first_watch=1, ready_notice_id=NULL")
        assert not await context.workflow.collector.ready(1, 2)

    asyncio.run(scenario())


def test_snapshot_failure_is_not_a_ready_cache(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)

        def broken(*_args, **_kwargs):
            raise BackfillError("synthetic verification read error")

        monkeypatch.setattr(context.workflow.collector.backfills, "readiness_snapshot", broken)
        with pytest.raises(CollectionUnavailable):
            await context.workflow.collector.ready(1, 2)
        notices = AsyncMock()
        await context.workflow.run(request(), context.channel, context.lease, notices)
        context.engine.summarize.assert_not_awaited()
        context.channel.send.assert_not_awaited()
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


@pytest.mark.parametrize("days", [1, 7, 30])
def test_current_cutoff_keeps_boundary_and_does_not_reject_full_duration_request(
    tmp_path, monkeypatch, days,
):
    async def scenario():
        context = runtime(tmp_path, monkeypatch, retention_days=days)
        cutoff = NOW - timedelta(days=days)
        context.messages.upsert(row(100, created_at=cutoff), cached_at=NOW)
        context.messages.upsert(row(101, created_at=cutoff + timedelta(seconds=2)), cached_at=NOW)
        context.messages.upsert(row(102, created_at=NOW - timedelta(seconds=1)), cached_at=NOW)
        initial = await collect(context, request(days=days))
        assert [item.message_id for item in initial.messages] == [100, 101, 102]
        assert isinstance(initial, CacheCollectionOutcome)
        context.clock.now += timedelta(seconds=1)
        selected = await collect(context, request(days=days))
        assert [item.message_id for item in selected.messages] == [101, 102]
        assert selected.searched_since == cutoff + timedelta(seconds=1)
        counted = await collect(context, request(kind=RequestKind.COUNT))
        assert [item.message_id for item in counted.messages] == [101, 102]
        assert counted.shortage == 1

    asyncio.run(scenario())


def test_expiration_during_a_database_read_is_removed_from_final_selection(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch, retention_days=1)
        context.messages.upsert(row(created_at=NOW - timedelta(days=1) + timedelta(seconds=1)),
                                cached_at=NOW)
        original = context.messages.recent

        def delayed(*args, **kwargs):
            selected = original(*args, **kwargs)
            context.clock.now += timedelta(seconds=2)
            return selected

        monkeypatch.setattr(context.messages, "recent", delayed)
        result = await collect(context)
        assert result.messages == ()
        assert result.searched_since == NOW - timedelta(days=1) + timedelta(seconds=2)

    asyncio.run(scenario())


def test_generation_change_during_collection_rejects_the_selection(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)
        original = context.messages.recent

        def changed(*args, **kwargs):
            selected = original(*args, **kwargs)
            completed_new_generation(context)
            return selected

        monkeypatch.setattr(context.messages, "recent", changed)
        with pytest.raises(BackfillNotReady):
            await collect(context)

    asyncio.run(scenario())


def test_generation_is_checked_after_the_final_external_permission_guard(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)
        calls = 0

        async def guard():
            nonlocal calls
            calls += 1
            if calls == 2:
                completed_new_generation(context)
            return True

        with pytest.raises(BackfillNotReady):
            await context.workflow.collector.collect(
                context.channel, guild_id=1, channel_id=2,
                request=request().requested_range, can_continue=guard,
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["pending", "completed", "expired", "gateway"])
def test_model_queue_cannot_release_a_stale_selection(tmp_path, monkeypatch, change):
    async def scenario():
        context = runtime(tmp_path, monkeypatch, retention_days=1)
        context.messages.upsert(row(created_at=NOW - timedelta(days=1) + timedelta(seconds=1)),
                                cached_at=NOW)
        waiting = asyncio.Event()

        class Queue(SummaryJobQueue):
            async def acquire(self, **kwargs):
                waiting.set()
                return await super().acquire(**kwargs)

        queue = Queue(concurrency=1, capacity=1, wait_seconds=5)
        held = await queue.acquire()
        waiting.clear()
        context.workflow.queue = queue
        task = asyncio.create_task(context.workflow.run(
            request(), context.channel, context.lease, AsyncMock(),
        ))
        await asyncio.wait_for(waiting.wait(), 3)
        if change == "pending":
            pending(context)
        elif change == "completed":
            completed_new_generation(context)
        elif change == "gateway":
            context.clock.available = False
        else:
            context.clock.now += timedelta(seconds=2)
        await held.__aexit__(None, None, None)
        await asyncio.wait_for(task, 3)
        context.engine.summarize.assert_not_awaited()
        context.channel.send.assert_not_awaited()
        assert await queue.snapshot() == (0, 0, False)
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


def test_repair_finishing_during_model_does_not_publish_old_input(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)

        async def summarize(*_args, **_kwargs):
            completed_new_generation(context)
            return SummaryResult("합성 대화를 정리했소.", "synthetic", 1)

        context.engine.summarize.side_effect = summarize
        notices = AsyncMock()
        await context.workflow.run(request(), context.channel, context.lease, notices)
        context.engine.summarize.assert_awaited_once()
        context.channel.send.assert_not_awaited()
        notices.assert_awaited_once_with(NOT_READY_NOTICE)
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


def test_recheck_while_model_is_running_cancels_model_without_publication(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def summarize(*_args, **_kwargs):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        context.engine.summarize.side_effect = summarize
        task = asyncio.create_task(context.workflow.run(
            request(), context.channel, context.lease, AsyncMock(),
        ))
        await asyncio.wait_for(entered.wait(), 3)
        pending(context)
        await asyncio.wait_for(task, 3)
        assert cancelled.is_set()
        context.channel.send.assert_not_awaited()
        assert await context.workflow.queue.snapshot() == (0, 0, False)
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())


def test_recheck_between_publication_parts_stops_without_a_success_cooldown(tmp_path, monkeypatch):
    async def scenario():
        context = runtime(tmp_path, monkeypatch)
        context.messages.upsert(row(), cached_at=NOW)
        monkeypatch.setattr("yoyackbot.publisher.format_summary", lambda *_args, **_kwargs: ["A", "B"])

        async def first_part(*_args, **_kwargs):
            pending(context)
            return SimpleNamespace(id=501, channel=context.channel, created_at=NOW)

        context.channel.send.side_effect = first_part
        await context.workflow.run(request(), context.channel, context.lease, AsyncMock())
        context.channel.send.assert_awaited_once()
        assert context.channel.send.await_args.args[0] == "A"
        assert await context.workflow.states.status(1, 2) is ChannelStatus.IDLE

    asyncio.run(scenario())
