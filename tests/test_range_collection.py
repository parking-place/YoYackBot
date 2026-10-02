"""Missing-range collection against a disposable SQLite cache."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.history import HistoryError, HistoryFailure, HistoryResult
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.range_collection import CollectionError, CollectionFailure, TimeRangeCollector
from yoyackbot.watch_store import SQLiteWatchStore

START = datetime(2026, 9, 28, 16, 20, tzinfo=UTC)
END = START + timedelta(hours=2)
FETCHED = END + timedelta(minutes=1)


def span(start: int, end: int) -> CoverageInterval:
    return CoverageInterval(10, START + timedelta(minutes=start), START + timedelta(minutes=end))


def record(message_id: int, minute: int, content: str = "synthetic") -> MessageRecord:
    return MessageRecord(
        message_id, 1, 10, 3, "synthetic author", content, START + timedelta(minutes=minute)
    )


def channel() -> SimpleNamespace:
    return SimpleNamespace(id=10, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)


class FakeHistory:
    def __init__(self, records, *, fail_on: int | None = None) -> None:
        self.records = records
        self.fail_on = fail_on
        self.calls: list[CoverageInterval] = []

    async def collect(
        self, target, *, guild_id, channel_id, start, end,
        trigger_message_id=None, can_continue=None,
    ):
        self.calls.append(CoverageInterval(channel_id, start, end))
        if len(self.calls) == self.fail_on:
            raise HistoryError(HistoryFailure.NETWORK)
        selected = tuple(
            item for item in self.records
            if start <= item.created_at < end and item.message_id != trigger_message_id
        )
        return HistoryResult(selected, 1)


def setup_store(tmp_path):
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10}))
    return SQLiteMessageStore(path, clock=lambda: FETCHED), watches


def test_overlap_fetches_only_two_gaps_then_zero(tmp_path) -> None:
    async def scenario() -> None:
        store, watches = setup_store(tmp_path)
        cached = record(101, 70)
        store.upsert(cached, cached_at=START)
        store.mark_covered(1, span(40, 100), verified_at=START)
        history = FakeHistory([record(100, 10), cached, record(102, 110)])
        collector = TimeRangeCollector(store, watches, history, clock=lambda: FETCHED)
        first = await collector.collect(channel(), guild_id=1, channel_id=10, start=START, end=END)
        assert history.calls == [span(0, 40), span(100, 120)]
        assert first.queried == tuple(history.calls)
        assert first.pages == 2
        assert [item.message_id for item in first.messages] == [100, 101, 102]
        second = await collector.collect(channel(), guild_id=1, channel_id=10, start=START, end=END)
        assert second.queried == () and second.pages == 0
        assert history.calls == [span(0, 40), span(100, 120)]
        assert [item.message_id for item in store.recent(1, 10, START, END)] == [100, 101, 102]

    asyncio.run(scenario())


def test_failed_second_gap_stays_missing_and_empty_first_gap_is_covered(tmp_path) -> None:
    async def scenario() -> None:
        store, watches = setup_store(tmp_path)
        store.mark_covered(1, span(40, 100), verified_at=START)
        history = FakeHistory([record(102, 110)], fail_on=2)
        collector = TimeRangeCollector(store, watches, history, clock=lambda: FETCHED)
        with pytest.raises(HistoryError) as failed:
            await collector.collect(channel(), guild_id=1, channel_id=10, start=START, end=END)
        assert failed.value.kind is HistoryFailure.NETWORK
        assert store.missing(1, span(0, 120)) == [span(100, 120)]
        assert store.recent(1, 10, START, END) == []
        retry = FakeHistory([record(102, 110)])
        result = await TimeRangeCollector(store, watches, retry, clock=lambda: FETCHED).collect(
            channel(), guild_id=1, channel_id=10, start=START, end=END
        )
        assert retry.calls == [span(100, 120)]
        assert [item.message_id for item in result.messages] == [102]

    asyncio.run(scenario())


def test_recheck_replaces_stale_edit_and_deleted_row(tmp_path) -> None:
    async def scenario() -> None:
        store, watches = setup_store(tmp_path)
        store.upsert(record(100, 10, "old"), cached_at=START)
        store.upsert(record(101, 20, "deleted"), cached_at=START)
        store.mark_covered(1, span(0, 120), verified_at=START)
        store.mark_all_watched_recheck(START, END, reason="gateway_gap")
        history = FakeHistory([replace(record(100, 10, "edited"), edited_at=END)])
        result = await TimeRangeCollector(store, watches, history, clock=lambda: FETCHED).collect(
            channel(), guild_id=1, channel_id=10, start=START, end=END
        )
        assert history.calls == [span(0, 120)]
        assert [(item.message_id, item.content) for item in result.messages] == [(100, "edited")]
        assert store.missing(1, span(0, 120)) == []

    asyncio.run(scenario())


def test_newer_gateway_edit_is_not_overwritten_by_older_history_page(tmp_path) -> None:
    async def scenario() -> None:
        store, watches = setup_store(tmp_path)

        class ConcurrentEdit(FakeHistory):
            async def collect(self, target, **kwargs):
                store.upsert(record(100, 10, "newer"), cached_at=FETCHED + timedelta(seconds=1))
                return await super().collect(target, **kwargs)

        history = ConcurrentEdit([record(100, 10, "older")])
        result = await TimeRangeCollector(store, watches, history, clock=lambda: FETCHED).collect(
            channel(), guild_id=1, channel_id=10, start=START, end=END
        )
        assert result.messages[0].content == "newer"

    asyncio.run(scenario())


def test_unwatched_or_mismatched_channel_cannot_use_cache(tmp_path) -> None:
    async def scenario() -> None:
        store, watches = setup_store(tmp_path)
        store.mark_covered(1, span(0, 120), verified_at=START)
        history = FakeHistory([])
        collector = TimeRangeCollector(store, watches, history, clock=lambda: FETCHED)
        wrong = SimpleNamespace(id=11, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)
        with pytest.raises(CollectionError) as mismatch:
            await collector.collect(wrong, guild_id=1, channel_id=10, start=START, end=END)
        assert mismatch.value.kind is CollectionFailure.CHANNEL_MISMATCH
        watches.replace(1, frozenset())
        with pytest.raises(CollectionError) as unwatched:
            await collector.collect(channel(), guild_id=1, channel_id=10, start=START, end=END)
        assert unwatched.value.kind is CollectionFailure.UNWATCHED
        assert history.calls == []

    asyncio.run(scenario())
