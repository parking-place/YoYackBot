"""Settings-verified cache fallback and empty collection contracts."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.collection import CollectionCoordinator, CollectionUnavailable, EMPTY_NOTICE
from yoyackbot.count_collection import CountCollector
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind
from yoyackbot.history import HistoryResult
from yoyackbot.long_range import LongRangeCollector, LongRangeError, LongRangeFailure
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.range_collection import TimeRangeCollector
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def channel():
    return SimpleNamespace(id=10, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)


def message(message_id=100, content="synthetic"):
    return MessageRecord(message_id, 1, 10, 3, "synthetic", content, NOW - timedelta(minutes=10))


class FakeHistory:
    def __init__(self, messages) -> None:
        self.messages = messages
        self.calls = []

    async def collect(self, target, *, start, end, limit_messages=None, **kwargs):
        self.calls.append((start, end, limit_messages))
        selected = [item for item in self.messages if start <= item.created_at < end]
        if limit_messages is not None:
            selected = sorted(selected, key=lambda item: item.created_at)[-limit_messages:]
        return HistoryResult(tuple(selected), 1, limit_messages is None or
                             len(selected) < limit_messages)


class BrokenStore(SQLiteMessageStore):
    def prune_before(self, cutoff):
        raise MessageStoreError("synthetic cache write failure")


def setup(tmp_path, history, *, broken=False, max_content_bytes=1_000_000):
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10}))
    store = BrokenStore(path) if broken else SQLiteMessageStore(path)
    recent = TimeRangeCollector(store, watches, history, clock=lambda: NOW)
    time = LongRangeCollector(recent, history, max_content_bytes=max_content_bytes)
    count = CountCollector(recent, history, max_content_bytes=max_content_bytes)
    coordinator = CollectionCoordinator(
        watches, time, count, history, max_content_bytes=max_content_bytes
    )
    return coordinator, store, watches


def test_cache_write_failure_falls_back_only_with_trusted_settings(tmp_path) -> None:
    async def scenario() -> None:
        healthy_history = FakeHistory([message()])
        healthy, _, _ = setup(tmp_path / "healthy", healthy_history)
        request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
        normal = await healthy.collect(channel(), guild_id=1, channel_id=10, request=request)
        assert not normal.fallback_used

        fallback_history = FakeHistory([message()])
        fallback, store, _ = setup(tmp_path / "fallback", fallback_history, broken=True)
        recovered = await fallback.collect(channel(), guild_id=1, channel_id=10, request=request)
        assert recovered.fallback_used
        assert [(item.message_id, item.content) for item in recovered.messages] == [
            (item.message_id, item.content) for item in normal.messages
        ]
        assert store.recent(1, 10, request.start, NOW) == []
        assert fallback_history.calls == [(request.start, NOW, None)]

    asyncio.run(scenario())


def test_settings_read_failure_stops_before_history(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([message()])
        coordinator, _, _ = setup(tmp_path, history, broken=True)

        class BrokenSettings:
            def snapshot(self, guild_id):
                raise WatchStoreError("synthetic settings failure")

        coordinator.watches = BrokenSettings()
        request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
        with pytest.raises(CollectionUnavailable):
            await coordinator.collect(channel(), guild_id=1, channel_id=10, request=request)
        assert history.calls == []

        fresh, _, stable_watches = setup(tmp_path / "after_cache_failure", history, broken=True)

        class FailingRecheck:
            def __init__(self):
                self.calls = 0

            def snapshot(self, guild_id):
                self.calls += 1
                if self.calls > 1:
                    raise WatchStoreError("synthetic settings failure after cache error")
                return stable_watches.snapshot(guild_id)

        fresh.watches = FailingRecheck()
        with pytest.raises(CollectionUnavailable):
            await fresh.collect(channel(), guild_id=1, channel_id=10, request=request)
        assert history.calls == []

    asyncio.run(scenario())


def test_empty_time_and_count_results_require_no_model(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([])
        coordinator, _, _ = setup(tmp_path, history)
        time_request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(minutes=30))
        empty_time = await coordinator.collect(
            channel(), guild_id=1, channel_id=10, request=time_request
        )
        assert empty_time.empty and not empty_time.requires_model
        assert empty_time.empty_notice == EMPTY_NOTICE

        count_request = RangeRequest(RequestKind.COUNT, NOW, count=1)
        empty_count = await coordinator.collect(
            channel(), guild_id=1, channel_id=10, request=count_request
        )
        assert empty_count.empty and not empty_count.requires_model
        assert empty_count.shortage == 1

    asyncio.run(scenario())


def test_fallback_count_and_input_budget(tmp_path) -> None:
    async def scenario() -> None:
        history = FakeHistory([message(100), message(101)])
        coordinator, _, _ = setup(tmp_path / "count", history, broken=True)
        request = RangeRequest(RequestKind.COUNT, NOW, count=3)
        result = await coordinator.collect(channel(), guild_id=1, channel_id=10, request=request)
        assert result.fallback_used and len(result.messages) == 2 and result.shortage == 1
        assert history.calls == [(NOW - timedelta(days=28), NOW, 3)]

        large_history = FakeHistory([message(content="too large")])
        limited, _, _ = setup(
            tmp_path / "limit", large_history, broken=True, max_content_bytes=3
        )
        time_request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
        with pytest.raises(LongRangeError) as failed:
            await limited.collect(channel(), guild_id=1, channel_id=10, request=time_request)
        assert failed.value.kind is LongRangeFailure.INPUT_LIMIT

    asyncio.run(scenario())
