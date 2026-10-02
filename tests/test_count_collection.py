"""Newest verified human count selection and bounded backfill."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord

from yoyackbot.count_collection import CountCollector
from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.history import HistoryAdapter, HistoryResult
from yoyackbot.input_files import serialize_conversation
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.range_collection import TimeRangeCollector
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def channel():
    return SimpleNamespace(id=10, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)


def record(message_id: int, minutes_ago: int) -> MessageRecord:
    return MessageRecord(message_id, 1, 10, 3, "synthetic", "body", NOW - timedelta(minutes=minutes_ago))


class FakeHistory:
    def __init__(self, messages) -> None:
        self.messages = messages
        self.calls = []

    async def collect(self, target, *, start, end, limit_messages=None, **kwargs):
        self.calls.append((start, end, limit_messages))
        selected = sorted(
            (item for item in self.messages if start <= item.created_at < end),
            key=lambda item: (item.created_at, item.message_id), reverse=True,
        )
        limited = selected[:limit_messages] if limit_messages is not None else selected
        return HistoryResult(tuple(reversed(limited)), 1, len(selected) <= len(limited))


def setup(tmp_path, history):
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    recent = TimeRangeCollector(store, watches, history, clock=lambda: NOW)
    return CountCollector(recent, history), store


def test_verified_cached_hundred_never_calls_history(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([])
        collector, store = setup(tmp_path, history)
        for minute in range(1, 101):
            store.upsert(record(minute, minute), cached_at=NOW)
        oldest = NOW - timedelta(minutes=100)
        store.mark_covered(1, CoverageInterval(10, oldest, NOW), verified_at=NOW)
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10, count=100, accepted_at=NOW,
        )
        assert len(result.messages) == 100 and result.shortage == 0
        assert [item.message_id for item in result.messages] == list(range(100, 0, -1))
        assert result.pages == 0 and history.calls == []

    asyncio.run(scenario())


def test_hundred_cached_with_middle_gap_fetches_hidden_newer_message(tmp_path) -> None:
    async def scenario() -> None:
        cached = [record(minute, minute) for minute in range(1, 101)]
        hidden = record(999, 25)
        history = FakeHistory([*cached, hidden])
        collector, store = setup(tmp_path, history)
        for item in cached:
            store.upsert(item, cached_at=NOW)
        store.mark_covered(
            1, CoverageInterval(10, NOW - timedelta(minutes=100), NOW - timedelta(minutes=30)),
            verified_at=NOW,
        )
        store.mark_covered(
            1, CoverageInterval(10, NOW - timedelta(minutes=20), NOW), verified_at=NOW,
        )
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10, count=100, accepted_at=NOW,
        )
        assert history.calls == [
            (NOW - timedelta(minutes=30), NOW - timedelta(minutes=20), None)
        ]
        assert len(result.messages) == 100 and result.shortage == 0
        assert result.messages[0].message_id == 99
        assert 999 in {item.message_id for item in result.messages}

    asyncio.run(scenario())


def test_shortage_searches_at_most_30_days_and_reports_actual_count(tmp_path) -> None:
    async def scenario() -> None:
        recent = record(1, 10)
        older = [
            MessageRecord(2, 1, 10, 3, "synthetic", "old", NOW - timedelta(days=10)),
            MessageRecord(3, 1, 10, 3, "synthetic", "older", NOW - timedelta(days=27)),
            MessageRecord(4, 1, 10, 3, "synthetic", "day29", NOW - timedelta(days=29)),
            MessageRecord(5, 1, 10, 3, "synthetic", "day31", NOW - timedelta(days=31)),
        ]
        history = FakeHistory([recent, *older])
        collector, store = setup(tmp_path, history)
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10, count=5, accepted_at=NOW,
        )
        assert [item.message_id for item in result.messages] == [4, 3, 2, 1]
        assert result.shortage == 1 and result.searched_since == NOW - timedelta(days=30)
        assert result.pages == 1
        assert [item.message_id for item in store.recent(
            1, 10, NOW - timedelta(days=30), NOW
        )] == [4, 3, 2, 1]
        assert history.calls == [(NOW - timedelta(days=30), NOW, None)]

    asyncio.run(scenario())


def test_lower_request_limit_does_not_use_older_cached_messages(tmp_path) -> None:
    async def scenario() -> None:
        old = MessageRecord(11, 1, 10, 3, "synthetic", "old", NOW - timedelta(days=10))
        fresh = record(12, 10)
        history = FakeHistory([old, fresh])
        path = tmp_path / "messages.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({10}))
        store = SQLiteMessageStore(path, clock=lambda: NOW)
        store.upsert(old, cached_at=NOW)
        store.upsert(fresh, cached_at=NOW)
        recent = TimeRangeCollector(store, watches, history, clock=lambda: NOW)
        collector = CountCollector(recent, history, retention_days=30, max_days=7)
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10, count=2, accepted_at=NOW,
        )
        assert [item.message_id for item in result.messages] == [12]
        assert result.shortage == 1
        assert all(start >= NOW - timedelta(days=7) for start, _, _ in history.calls)

    asyncio.run(scenario())


def test_large_count_sizes_reach_input_preparation_without_missing_rows(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([])
        collector, store = setup(tmp_path, history)
        for minute in range(1, 1001):
            store.upsert(record(minute, minute), cached_at=NOW)
        store.mark_covered(
            1, CoverageInterval(10, NOW - timedelta(minutes=1000), NOW), verified_at=NOW,
        )
        for count in (101, 150, 200, 300, 500, 858, 1000):
            outcome = await collector.collect(
                channel(), guild_id=1, channel_id=10, count=count, accepted_at=NOW,
            )
            assert len(outcome.messages) == count
            assert len({item.message_id for item in outcome.messages}) == count
            document = serialize_conversation(
                outcome.messages, channel_name="synthetic", range_label="count",
                trigger_message_id=None, max_bytes=1_000_000,
            )
            assert len(document) > count and len(document) < 1_000_000
            assert outcome.pages == 0
        assert history.calls == []

    asyncio.run(scenario())


def test_discord_source_filters_bot_webhook_and_trigger_before_counting(tmp_path) -> None:
    async def scenario() -> None:
        messages = []
        for minute in range(1, 102):
            at = NOW - timedelta(minutes=minute)
            messages.append(SimpleNamespace(
                id=discord.utils.time_snowflake(at) + minute,
                guild=SimpleNamespace(id=1), channel=channel(),
                author=SimpleNamespace(id=3, bot=False, display_name="synthetic"),
                webhook_id=None, type=discord.MessageType.default,
                content="body", created_at=at, edited_at=None,
            ))
        for minute, bot, webhook in ((101, True, None), (102, False, 7)):
            at = NOW - timedelta(minutes=minute)
            messages.append(SimpleNamespace(
                id=discord.utils.time_snowflake(at),
                guild=SimpleNamespace(id=1), channel=channel(),
                author=SimpleNamespace(id=3, bot=bot, display_name="synthetic"),
                webhook_id=webhook, type=discord.MessageType.default,
                content="excluded", created_at=at, edited_at=None,
            ))
        trigger = messages[0]
        source = SimpleNamespace()
        source.calls = 0

        async def fetch_page(target, *, before, limit):
            source.calls += 1
            return sorted(
                (item for item in messages if item.id < before),
                key=lambda item: item.id, reverse=True,
            )[:limit]

        source.fetch_page = fetch_page
        history = HistoryAdapter(source, page_size=20, max_pages=20)
        collector, _ = setup(tmp_path, history)
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10, count=100, accepted_at=NOW,
            trigger_message_id=trigger.id,
        )
        assert len(result.messages) == 100 and result.shortage == 0
        assert trigger.id not in {item.message_id for item in result.messages}
        assert all(item.content == "body" for item in result.messages)
        assert source.calls > 1

    asyncio.run(scenario())
