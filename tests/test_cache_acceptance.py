"""Concurrent cache operations and bounded, classified storage failures."""

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.discord import YoYackClient
from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.message_store import CacheFailureKind, MessageStoreError, SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def record(message_id: int, guild_id: int, created_at: datetime = NOW) -> MessageRecord:
    return MessageRecord(message_id, guild_id, 10, 3, "synthetic", "synthetic", created_at)


def test_concurrent_ingest_read_and_cleanup_do_not_mix_guilds_or_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watched = SQLiteWatchStore(path)
    watched.replace(1, frozenset({10}))
    watched.replace(2, frozenset({10}))
    store = SQLiteMessageStore(path)
    interval = CoverageInterval(10, NOW - timedelta(days=2), NOW + timedelta(seconds=1))

    with ThreadPoolExecutor(max_workers=8) as workers:
        tasks = []
        for guild_id in (1, 2):
            for offset in range(30):
                message = record(guild_id * 1000 + offset, guild_id)
                for _ in range(2):
                    tasks.append(
                        workers.submit(
                            store.upsert_if_watched,
                            message,
                            expected_version=1,
                            cached_at=NOW,
                        )
                    )
        tasks.append(workers.submit(store.mark_covered, 1, interval, verified_at=NOW))
        tasks.append(workers.submit(store.prune_before, NOW - timedelta(days=7)))
        tasks.append(workers.submit(store.recent, 1, 10, NOW, NOW + timedelta(seconds=1)))
        for task in tasks:
            task.result(timeout=15)

    store.upsert(record(999, 1, NOW - timedelta(days=8)), cached_at=NOW)
    assert store.prune_before(NOW - timedelta(days=7)) == 1
    for guild_id in (1, 2):
        found = store.recent(guild_id, 10, NOW, NOW + timedelta(seconds=1))
        assert len(found) == 30
        assert len({item.message_id for item in found}) == 30
        assert all(item.guild_id == guild_id for item in found)
    assert store.coverage(1, 10) == [interval]
    assert store.coverage(2, 10) == []


def test_locked_readonly_full_and_corrupt_failures_have_safe_categories(tmp_path) -> None:
    path = tmp_path / "messages.db"
    store = SQLiteMessageStore(path)
    with sqlite3.connect(path) as lock:
        lock.execute("BEGIN EXCLUSIVE")
        with pytest.raises(MessageStoreError) as locked:
            store.upsert(record(100, 1), cached_at=NOW)
    assert locked.value.kind is CacheFailureKind.LOCKED
    assert "synthetic" not in str(locked.value)

    class ReadOnlyStore(SQLiteMessageStore):
        @contextmanager
        def _connection(self):
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            try:
                yield connection
            finally:
                connection.close()

    with pytest.raises(MessageStoreError) as read_only:
        ReadOnlyStore(path).upsert(record(101, 1), cached_at=NOW)
    assert read_only.value.kind is CacheFailureKind.READ_ONLY

    class FullStore(SQLiteMessageStore):
        @contextmanager
        def _connection(self):
            connection = sqlite3.connect(self.path)
            try:
                pages = connection.execute("PRAGMA page_count").fetchone()[0]
                connection.execute(f"PRAGMA max_page_count={pages}")
                yield connection
            finally:
                connection.close()

    with pytest.raises(MessageStoreError) as full:
        FullStore(path).upsert(
            MessageRecord(102, 1, 10, 3, "synthetic", "x" * 100_000, NOW), cached_at=NOW
        )
    assert full.value.kind is CacheFailureKind.FULL
    assert "x" * 20 not in str(full.value)

    path.write_bytes(b"not a sqlite database")
    with pytest.raises(MessageStoreError) as corrupt:
        store.recent(1, 10, NOW, NOW + timedelta(seconds=1))
    assert corrupt.value.kind is CacheFailureKind.CORRUPT


def test_locked_watch_lookup_does_not_block_gateway_event_loop(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watched = SQLiteWatchStore(path)
        watched.replace(1, frozenset({10}))
        client = YoYackClient(watch_store=watched)
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(type=discord.ChannelType.text, id=10),
            author=SimpleNamespace(bot=False),
            webhook_id=None,
            type=discord.MessageType.default,
            content="synthetic ordinary message",
        )
        lock = sqlite3.connect(path)
        try:
            lock.execute("BEGIN EXCLUSIVE")
            pending = asyncio.create_task(client.on_message(message))
            await asyncio.sleep(0.05)
            assert not pending.done()
            lock.rollback()
            await asyncio.wait_for(pending, timeout=2)
        finally:
            lock.close()
            await client.close()

    asyncio.run(scenario())
