"""Four-week requests keep older message bodies out of persistent storage."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.domain import MessageRecord
from yoyackbot.history import HistoryResult
from yoyackbot.long_range import LongRangeCollector, LongRangeError, LongRangeFailure
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.range_collection import TimeRangeCollector
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def message(message_id: int, days_ago: int, content: str = "synthetic") -> MessageRecord:
    return MessageRecord(message_id, 1, 10, 3, "synthetic", content, NOW - timedelta(days=days_ago))


def channel():
    return SimpleNamespace(id=10, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)


class FakeHistory:
    def __init__(self, messages, *, cancel: bool = False) -> None:
        self.messages = messages
        self.calls = []
        self.cancel = cancel

    async def collect(self, target, *, start, end, **kwargs):
        self.calls.append((start, end))
        if self.cancel:
            raise asyncio.CancelledError
        return HistoryResult(
            tuple(item for item in self.messages if start <= item.created_at < end), 1
        )


def setup(tmp_path, history, **limits):
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    recent = TimeRangeCollector(store, watches, history, clock=lambda: NOW)
    collector = LongRangeCollector(recent, history, **{
        "retention_days": 7, "max_days": 28, **limits,
    })
    return collector, store


@pytest.mark.parametrize("days", [14, 28])
def test_two_and_four_week_range_joins_without_persisting_old_messages(tmp_path, days) -> None:
    async def scenario() -> None:
        old = message(100, days - 1)
        fresh = message(101, 1)
        history = FakeHistory([old, fresh])
        collector, store = setup(tmp_path, history)
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10,
            start=NOW - timedelta(days=days), end=NOW, accepted_at=NOW,
        )
        assert [item.message_id for item in result.messages] == [100, 101]
        assert result.older_count == 1 and result.pages == 2
        assert history.calls == [
            (NOW - timedelta(days=days), NOW - timedelta(days=7)),
            (NOW - timedelta(days=7), NOW),
        ]
        assert [item.message_id for item in store.recent(
            1, 10, NOW - timedelta(days=days), NOW
        )] == [101]
        assert all(item.start >= NOW - timedelta(days=7) for item in store.coverage(1, 10))
        assert sorted(item.name for item in tmp_path.iterdir()) == ["messages.db"]

    asyncio.run(scenario())


def test_more_than_four_weeks_is_rejected_before_history_or_db_mutation(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([])
        collector, store = setup(tmp_path, history)
        with pytest.raises(LongRangeError) as failed:
            await collector.collect(
                channel(), guild_id=1, channel_id=10,
                start=NOW - timedelta(days=28, seconds=1), end=NOW, accepted_at=NOW,
            )
        assert failed.value.kind is LongRangeFailure.TOO_OLD
        assert history.calls == [] and store.coverage(1, 10) == []

    asyncio.run(scenario())


@pytest.mark.parametrize("age", [6, 7, 8, 29, 30])
def test_thirty_day_cache_includes_boundary_and_rejects_day_31(tmp_path, age) -> None:
    async def scenario() -> None:
        included = message(100, age)
        excluded = message(101, 31)
        history = FakeHistory([included, excluded])
        collector, store = setup(
            tmp_path, history, retention_days=30, max_days=30
        )
        result = await collector.collect(
            channel(), guild_id=1, channel_id=10,
            start=NOW - timedelta(days=30), end=NOW, accepted_at=NOW,
        )
        assert [item.message_id for item in result.messages] == [100]
        assert result.older_count == 0 and result.pages == 1
        assert history.calls == [(NOW - timedelta(days=30), NOW)]
        assert [item.message_id for item in store.recent(
            1, 10, NOW - timedelta(days=30), NOW
        )] == [100]
        with pytest.raises(LongRangeError) as failed:
            await collector.collect(
                channel(), guild_id=1, channel_id=10,
                start=NOW - timedelta(days=31), end=NOW, accepted_at=NOW,
            )
        assert failed.value.kind is LongRangeFailure.TOO_OLD

    asyncio.run(scenario())


def test_content_and_total_page_limits_fail_instead_of_truncating(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([message(100, 8, "abcdefgh"), message(101, 1)])
        small, _ = setup(tmp_path / "small", history, max_content_bytes=4)
        with pytest.raises(LongRangeError) as too_large:
            await small.collect(
                channel(), guild_id=1, channel_id=10,
                start=NOW - timedelta(days=14), end=NOW, accepted_at=NOW,
            )
        assert too_large.value.kind is LongRangeFailure.INPUT_LIMIT
        assert len(history.calls) == 1

        page_history = FakeHistory([message(100, 8), message(101, 1)])
        limited, _ = setup(tmp_path / "pages", page_history, max_pages=1)
        with pytest.raises(LongRangeError) as too_many:
            await limited.collect(
                channel(), guild_id=1, channel_id=10,
                start=NOW - timedelta(days=14), end=NOW, accepted_at=NOW,
            )
        assert too_many.value.kind is LongRangeFailure.PAGE_LIMIT

    asyncio.run(scenario())


def test_cancellation_leaves_no_old_content_or_request_file(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([message(100, 8)], cancel=True)
        collector, store = setup(tmp_path, history)
        with pytest.raises(asyncio.CancelledError):
            await collector.collect(
                channel(), guild_id=1, channel_id=10,
                start=NOW - timedelta(days=14), end=NOW, accepted_at=NOW,
            )
        assert store.recent(1, 10, NOW - timedelta(days=14), NOW) == []
        assert sorted(item.name for item in tmp_path.iterdir()) == ["messages.db"]

    asyncio.run(scenario())
