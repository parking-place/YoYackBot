"""Current retention, edit ordering, and reconnect reservation at the Gateway boundary."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.backfill import BackfillError
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import MessageRecord
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def test_failed_gap_reservation_blocks_cache_until_worker_retry(caplog) -> None:
    async def scenario() -> None:
        clock = [NOW]
        client = YoYackClient(clock=lambda: clock[0])
        # The actual method is synchronous and dispatched through to_thread.
        attempts = []

        def schedule(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise BackfillError("private failure detail")
            return 1

        client.backfill_store = SimpleNamespace(schedule_ready_recheck=schedule)
        client._resume_accessible_backfills = AsyncMock()
        try:
            await client.on_disconnect()
            clock[0] += timedelta(seconds=5)
            await client.on_disconnect()
            assert client._disconnected_at == NOW
            await client.on_resumed()
            assert client.ready_event.is_set()
            assert not client.cache_available()
            assert client._disconnected_at == NOW
            client.initial_backfill = object()
            client.backfill_notifier = object()
            client.backfill_scheduler = object()

            def pending(_now):
                # Reaching pending proves the worker retried reservation successfully.
                assert client.cache_available()
                raise asyncio.CancelledError

            client.backfill_store.pending = pending
            with pytest.raises(asyncio.CancelledError):
                await client._backfill_loop()
            assert len(attempts) == 2
            assert all(attempt["start"] == NOW for attempt in attempts)
            assert client._disconnected_at is None
            assert "private failure detail" not in caplog.text
        finally:
            await client.close()

    asyncio.run(scenario())


def test_new_disconnect_while_reserving_does_not_clear_the_new_gap() -> None:
    async def scenario() -> None:
        client = YoYackClient(clock=lambda: NOW)
        loop = asyncio.get_running_loop()

        def schedule(**_kwargs):
            asyncio.run_coroutine_threadsafe(client.on_disconnect(), loop).result(timeout=2)
            return 1

        client.backfill_store = SimpleNamespace(schedule_ready_recheck=schedule)
        client._resume_accessible_backfills = AsyncMock()
        try:
            await client.on_disconnect()
            await client.on_resumed()
            assert not client.cache_available()
            assert not client.ready_event.is_set()
            assert client._disconnected_at == NOW
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("stamp", [None, "invalid", "2026-10-02T12:00:00"])
def test_unknown_raw_timestamp_does_not_invent_a_new_edit(tmp_path, stamp) -> None:
    async def scenario() -> None:
        path = tmp_path / "cache.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({10}))
        messages = SQLiteMessageStore(path, clock=lambda: NOW)
        created = NOW - timedelta(hours=1)
        messages.upsert(
            MessageRecord(100, 1, 10, 3, "Synthetic", "confirmed", created,
                          edited_at=created + timedelta(minutes=1)), cached_at=NOW,
        )
        client = YoYackClient(watch_store=watches, message_store=messages, clock=lambda: NOW)
        try:
            data = {"content": "unconfirmed"}
            if stamp is not None:
                data["edited_timestamp"] = stamp
            await client.on_raw_message_edit(SimpleNamespace(
                guild_id=1, channel_id=10, message_id=100, data=data,
            ))
            row, = messages.recent(1, 10, created, NOW)
            assert row.content == "confirmed"
            assert row.edited_at == created + timedelta(minutes=1)
            assert messages.recheck(1, 10)
        finally:
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("days", [1, 7, 30])
def test_gateway_writes_recheck_current_cutoff_and_never_revive_expired_cache(tmp_path, days) -> None:
    async def scenario() -> None:
        path = tmp_path / "cache.db"
        now = [NOW]
        settings = Settings.from_environment({
            "DISCORD_BOT_TOKEN": "test-token", "YOYACK_DB_PATH": str(path),
            "YOYACK_CACHE_RETENTION_DAYS": str(days),
        })
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({10}))
        messages = SQLiteMessageStore(path, clock=lambda: now[0], retention_days=days)
        client = YoYackClient(
            watch_store=watches, message_store=messages, settings=settings, clock=lambda: now[0],
        )
        floor = NOW - timedelta(days=days)
        guild = SimpleNamespace(id=1)
        channel = SimpleNamespace(id=10, type=discord.ChannelType.text)

        def event(message_id, created_at, *, edited_at=None):
            return SimpleNamespace(
                id=message_id, guild=guild, channel=channel, webhook_id=None,
                author=SimpleNamespace(id=3, bot=False, display_name="Synthetic"),
                type=discord.MessageType.default, content="retained synthetic body",
                created_at=created_at, edited_at=edited_at,
            )

        try:
            for message_id, delta in ((100, -1), (101, 0), (102, 1)):
                await client.on_message(event(message_id, floor + timedelta(microseconds=delta)))
            with sqlite3.connect(path) as connection:
                assert connection.execute("SELECT message_id FROM messages ORDER BY message_id").fetchall() == [(101,), (102,)]
            now[0] += timedelta(seconds=1)
            await client._prune_once()
            await client.on_message_edit(None, event(101, floor, edited_at=now[0]))
            await client.on_raw_message_edit(SimpleNamespace(
                guild_id=1, channel_id=10, message_id=102,
                data={"content": "expired edit", "edited_timestamp": now[0].isoformat()},
            ))
            with sqlite3.connect(path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM messages").fetchone() == (0,)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_cached_edit_without_timestamp_preserves_confirmed_body_and_rechecks(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "cache.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({10}))
        messages = SQLiteMessageStore(path, clock=lambda: NOW)
        created = NOW - timedelta(hours=1)
        messages.upsert(MessageRecord(100, 1, 10, 3, "Synthetic", "confirmed", created), cached_at=NOW)
        client = YoYackClient(watch_store=watches, message_store=messages, clock=lambda: NOW)
        after = SimpleNamespace(
            id=100, guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(id=10, type=discord.ChannelType.text),
            author=SimpleNamespace(id=3, bot=False), webhook_id=None,
            type=discord.MessageType.default, content="ambiguous cached edit", edited_at=None,
        )
        try:
            await client.on_message_edit(SimpleNamespace(content="confirmed"), after)
            row, = messages.recent(1, 10, created, NOW)
            assert row.content == "confirmed"
            assert messages.recheck(1, 10)
        finally:
            await client.close()

    asyncio.run(scenario())
