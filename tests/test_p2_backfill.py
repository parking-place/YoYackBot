"""P2: reconcile complete retained pages, invalidate work generations, and bound retention."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.backfill import BackfillError, InitialBackfill, SQLiteBackfillStore
from yoyackbot.domain import MessageRecord
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def message(when: datetime, number: int, content: str = "합성 본문") -> SimpleNamespace:
    return SimpleNamespace(
        id=discord.utils.time_snowflake(when) + number, created_at=when, edited_at=None,
        guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=99),
        author=SimpleNamespace(id=7, display_name="합성 화자", bot=False), webhook_id=None,
        content=content, type=discord.MessageType.default, attachments=(),
    )


def record(item: SimpleNamespace) -> MessageRecord:
    return MessageRecord(item.id, 1, 99, 7, "합성 화자", item.content, item.created_at, item.edited_at)


class Pages:
    def __init__(self, items=()) -> None:
        self.items = list(items)
        self.calls = []
        self.failure = False

    async def fetch_page(self, channel, *, before: int, limit: int, after: int | None = None):
        self.calls.append((before, after, limit))
        if self.failure:
            raise OSError("synthetic History interruption")
        return sorted(
            (item for item in self.items if (after or 0) < item.id < before),
            key=lambda item: item.id, reverse=True,
        )[:limit]


def setup(tmp_path, *, retention_days: int = 30):
    now = [NOW]
    path = tmp_path / "messages.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE backfill_state SET first_watch=0")
    store = SQLiteBackfillStore(path, retention_days=retention_days, clock=lambda: now[0])
    messages = SQLiteMessageStore(path, retention_days=retention_days, clock=lambda: now[0])
    store.schedule_ready_recheck(end=now[0])
    channel = SimpleNamespace(id=99, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)
    return now, path, store, messages, channel


async def finish(worker, store, channel) -> None:
    for _ in range(30):
        state = store.get(1, 99)
        assert state is not None
        if state.ready:
            return
        assert await worker.step(channel, state)
    raise AssertionError("bounded synthetic History did not finish")


def test_reconnect_reconciles_old_edits_and_offline_deletions(tmp_path) -> None:
    now, _path, store, messages, channel = setup(tmp_path)
    edited = message(now[0] - timedelta(days=10), 1)
    deleted = message(now[0] - timedelta(days=9), 2)
    for item in (edited, deleted):
        messages.upsert(record(item), cached_at=now[0])
    now[0] += timedelta(hours=2)
    edited.content, edited.edited_at = "오프라인 중 바뀐 본문", now[0] - timedelta(minutes=1)
    store.schedule_ready_recheck(start=now[0] - timedelta(hours=1), end=now[0])
    worker = InitialBackfill(store, Pages([edited]), page_size=1)
    assert store.readiness_snapshot(1, 99, cutoff=now[0] - timedelta(days=30))[2]
    asyncio.run(finish(worker, store, channel))
    rows = messages.recent(1, 99, now[0] - timedelta(days=30), now[0])
    assert [(row.message_id, row.content) for row in rows] == [(edited.id, edited.content)]
    state, generation, pending = store.readiness_snapshot(
        1, 99, cutoff=now[0] - timedelta(days=30),
    )
    assert state.ready and generation == state.started_us and not pending


def test_completed_empty_history_deletes_but_failed_tail_keeps_unvisited_cache(tmp_path) -> None:
    now, _path, store, messages, channel = setup(tmp_path)
    old = message(now[0] - timedelta(hours=4), 1)
    recent = message(now[0] - timedelta(hours=1), 2)
    for item in (old, recent):
        messages.upsert(record(item), cached_at=now[0])
    source = Pages([recent])
    worker = InitialBackfill(store, source, page_size=1)

    async def scenario() -> None:
        assert await worker.step(channel, store.get(1, 99))
        cursor = store.get(1, 99).cursor
        assert old.id in {row.message_id for row in messages.recent(
            1, 99, now[0] - timedelta(days=1), now[0],
        )}
        source.failure = True
        with pytest.raises(BackfillError):
            await worker.step(channel, store.get(1, 99))
        assert store.get(1, 99).cursor == cursor
        assert store.readiness_snapshot(1, 99, cutoff=now[0] - timedelta(days=30))[2]
        source.failure = False
        await finish(worker, store, channel)
        assert [row.message_id for row in messages.recent(
            1, 99, now[0] - timedelta(days=1), now[0],
        )] == [recent.id]
        source.items.clear()
        store.schedule_ready_recheck(end=now[0])
        await finish(worker, store, channel)
        assert messages.recent(1, 99, now[0] - timedelta(days=1), now[0]) == []

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["history", "overlap", "ready"])
def test_restart_from_every_phase_fetches_new_gap_before_ready(tmp_path, phase: str) -> None:
    now, path, store, messages, channel = setup(tmp_path)
    source = Pages()
    worker = InitialBackfill(store, source)

    async def scenario() -> None:
        if phase in {"overlap", "ready"}:
            assert await worker.step(channel, store.get(1, 99))
        if phase == "ready":
            assert await worker.step(channel, store.get(1, 99))
        previous = store.get(1, 99)
        assert previous.phase == phase
        now[0] += timedelta(hours=1)
        arrival = message(now[0] - timedelta(minutes=1), 4)
        source.items.append(arrival)
        reopened = SQLiteBackfillStore(path, clock=lambda: now[0])
        assert reopened.schedule_ready_recheck(end=now[0]) == 1
        current = reopened.get(1, 99)
        assert current.phase == "history" and current.started_us > previous.started_us
        assert current.token == previous.token
        assert not reopened.save_page(
            previous, (), next_cursor=previous.cursor, next_phase="ready",
            finished_at=now[0], cached_at=now[0],
        )
        await finish(InitialBackfill(reopened, source), reopened, channel)
        assert [row.message_id for row in messages.recent(
            1, 99, now[0] - timedelta(days=1), now[0],
        )] == [arrival.id]

    asyncio.run(scenario())


def test_same_tick_reset_invalidates_inflight_page_even_with_same_cursor(tmp_path) -> None:
    now, _path, store, messages, channel = setup(tmp_path)
    item = message(now[0] - timedelta(minutes=1), 1)

    class Reconnected(Pages):
        async def fetch_page(self, *args, **kwargs):
            page = await super().fetch_page(*args, **kwargs)
            store.schedule_ready_recheck(end=now[0])
            return page

    original = store.get(1, 99)
    assert not asyncio.run(InitialBackfill(store, Reconnected([item])).step(channel, original))
    current = store.get(1, 99)
    assert current.cursor == original.cursor and current.started_us > original.started_us
    assert messages.recent(1, 99, now[0] - timedelta(days=1), now[0]) == []
    assert store.readiness_snapshot(1, 99, cutoff=now[0] - timedelta(days=30))[2]


def test_unknown_raw_edit_invalidates_page_and_worker_consumes_pending(tmp_path) -> None:
    now, _path, store, messages, channel = setup(tmp_path)
    item = message(now[0] - timedelta(hours=1), 1)
    messages.upsert(record(item), cached_at=now[0])

    class AmbiguousEdit(Pages):
        async def fetch_page(self, *args, **kwargs):
            page = await super().fetch_page(*args, **kwargs)
            assert not messages.update_content(
                1, 99, item.id, "시각 없는 원시 이벤트", edited_at=None, cached_at=now[0],
            )
            return page

    original = store.get(1, 99)
    assert not asyncio.run(InitialBackfill(store, AmbiguousEdit([item])).step(channel, original))
    pending = store.pending(now[0])
    assert len(pending) == 1 and pending[0].started_us > original.started_us
    item.content, item.edited_at = "History에서 확인한 본문", now[0]
    asyncio.run(finish(InitialBackfill(store, Pages([item])), store, channel))
    assert not store.readiness_snapshot(1, 99, cutoff=now[0] - timedelta(days=30))[2]
    assert messages.recent(1, 99, now[0] - timedelta(days=1), now[0])[0].content == item.content


def test_second_disconnect_during_overlap_keeps_both_arrivals(tmp_path) -> None:
    now, _path, store, messages, channel = setup(tmp_path)
    original = message(now[0] - timedelta(minutes=5), 1)
    source = Pages([original])
    worker = InitialBackfill(store, source)

    async def scenario() -> None:
        assert await worker.step(channel, store.get(1, 99))
        first_overlap = store.get(1, 99)
        assert first_overlap.phase == "overlap"
        now[0] += timedelta(minutes=10)
        first = message(now[0] - timedelta(minutes=1), 2)
        source.items.append(first)
        store.schedule_ready_recheck(end=now[0])
        assert await worker.step(channel, store.get(1, 99))
        second_overlap = store.get(1, 99)
        assert second_overlap.phase == "overlap"
        now[0] += timedelta(minutes=10)
        second = message(now[0] - timedelta(minutes=1), 3)
        source.items.append(second)
        store.schedule_ready_recheck(end=now[0])
        assert not await worker.step(channel, second_overlap)
        assert store.readiness_snapshot(1, 99, cutoff=now[0] - timedelta(days=30))[2]
        await finish(worker, store, channel)
        assert {row.message_id for row in messages.recent(
            1, 99, now[0] - timedelta(days=1), now[0],
        )} == {original.id, first.id, second.id}

    asyncio.run(scenario())


def test_retention_shrink_after_long_pause_limits_resumed_fetch(tmp_path) -> None:
    now, path, store, messages, channel = setup(tmp_path)
    initial = store.get(1, 99)
    now[0] += timedelta(days=10)
    cutoff = now[0] - timedelta(days=1)
    expired = message(cutoff - timedelta(seconds=1), 1)
    retained = message(cutoff, 2)
    shortened = SQLiteBackfillStore(path, retention_days=1, clock=lambda: now[0])
    shortened.schedule_ready_recheck(end=now[0])
    source = Pages([expired, retained])
    asyncio.run(finish(InitialBackfill(shortened, source), shortened, channel))
    assert source.calls[0][1] == discord.utils.time_snowflake(cutoff) - 1
    assert shortened.get(1, 99).started_us > initial.started_us
    assert [row.message_id for row in messages.recent(
        1, 99, now[0] - timedelta(days=30), now[0],
    )] == [retained.id]


@pytest.mark.parametrize("days", [1, 7, 30])
def test_fetch_and_commit_apply_current_retention_inclusive_boundary(tmp_path, days: int) -> None:
    now, _path, store, messages, channel = setup(tmp_path, retention_days=days)
    cutoff = now[0] - timedelta(days=days)
    items = [
        message(cutoff - timedelta(milliseconds=1), 1),
        message(cutoff, 2), message(cutoff + timedelta(milliseconds=1), 3),
    ]
    source = Pages(items)
    asyncio.run(finish(InitialBackfill(store, source), store, channel))
    assert source.calls[0][1] == discord.utils.time_snowflake(cutoff) - 1
    assert {row.message_id for row in messages.recent(
        1, 99, cutoff - timedelta(days=1), now[0],
    )} == {items[1].id, items[2].id}


def test_page_aging_out_during_fetch_is_not_written(tmp_path) -> None:
    now, _path, store, messages, channel = setup(tmp_path, retention_days=1)
    item = message(now[0] - timedelta(days=1) + timedelta(seconds=1), 1)

    class Slow(Pages):
        async def fetch_page(self, *args, **kwargs):
            page = await super().fetch_page(*args, **kwargs)
            now[0] += timedelta(seconds=2)
            return page

    assert asyncio.run(InitialBackfill(store, Slow([item])).step(channel, store.get(1, 99)))
    assert messages.recent(1, 99, now[0] - timedelta(days=2), now[0]) == []


@pytest.mark.parametrize("event", ["edit", "delete"])
def test_same_clock_live_event_during_history_fetch_wins(tmp_path, event: str) -> None:
    now, _path, store, messages, channel = setup(tmp_path)
    item = message(now[0] - timedelta(hours=1), 1)
    original = record(item)
    messages.upsert(original, cached_at=now[0])

    class LiveEvent(Pages):
        async def fetch_page(self, *args, **kwargs):
            page = await super().fetch_page(*args, **kwargs)
            if event == "edit":
                messages.upsert(replace(original, content="새로운 본문", edited_at=now[0]),
                                cached_at=now[0])
            else:
                messages.delete_many(1, 99, {item.id})
            return page

    assert asyncio.run(InitialBackfill(store, LiveEvent([item])).step(channel, store.get(1, 99)))
    rows = messages.recent(1, 99, now[0] - timedelta(days=1), now[0])
    assert [row.content for row in rows] == (["새로운 본문"] if event == "edit" else [])
