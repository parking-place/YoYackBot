"""Verified History intervals, recheck gaps, and atomic completion."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from yoyackbot.config import Settings
from yoyackbot.coverage import merge_intervals, missing_intervals
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def interval(start: int, end: int) -> CoverageInterval:
    return CoverageInterval(10, NOW + timedelta(minutes=start), NOW + timedelta(minutes=end))


def test_merge_and_subtract_disjoint_adjacent_overlapping_and_nested_intervals() -> None:
    assert merge_intervals(10, [interval(10, 20), interval(0, 10), interval(5, 15)]) == [
        interval(0, 20)
    ]
    assert merge_intervals(10, [interval(0, 5), interval(10, 20)]) == [
        interval(0, 5), interval(10, 20)
    ]
    assert missing_intervals(interval(0, 30), [interval(0, 5), interval(10, 20)]) == [
        interval(5, 10), interval(20, 30)
    ]
    assert missing_intervals(interval(5, 15), [interval(0, 30)]) == []
    assert missing_intervals(interval(0, 10), []) == [interval(0, 10)]
    assert missing_intervals(
        interval(0, 30), [interval(0, 30)], recheck=[interval(5, 10), interval(15, 25)]
    ) == [interval(5, 10), interval(15, 25)]
    with pytest.raises(ValueError):
        merge_intervals(10, [CoverageInterval(11, NOW, NOW + timedelta(minutes=1))])


def test_history_only_marks_coverage_after_full_exhaustion_and_valid_watch(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watched = SQLiteWatchStore(path)
    version = watched.replace(1, frozenset({10}))
    store = SQLiteMessageStore(path)
    request = interval(0, 30)
    record = MessageRecord(100, 1, 10, 3, "author", "synthetic", NOW)
    assert store.missing(1, request) == [request]
    assert not store.commit_history_complete(
        1, request, [record], exhausted=False, expected_version=version, verified_at=NOW
    )
    assert store.recent(1, 10, NOW, NOW + timedelta(minutes=30)) == []
    assert store.missing(1, request) == [request]
    assert store.commit_history_complete(
        1, request, [record], exhausted=True, expected_version=version, verified_at=NOW
    )
    assert [item.message_id for item in store.recent(1, 10, NOW, NOW + timedelta(minutes=30))] == [100]
    assert store.missing(1, request) == []
    watched.replace(1, frozenset())
    assert not store.commit_history_complete(
        1, request, [record], exhausted=True, expected_version=version, verified_at=NOW
    )
    assert store.missing(1, request) == [request]


def test_recheck_survives_restarts_and_is_cleared_only_for_completed_subrange(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watched = SQLiteWatchStore(path)
    version = watched.replace(1, frozenset({10}))
    store = SQLiteMessageStore(path)
    request = interval(0, 30)
    store.mark_covered(1, request, verified_at=NOW)
    assert store.mark_all_watched_recheck(request.start, request.end, reason="startup") == 1
    assert store.missing(1, request) == [request]
    assert SQLiteMessageStore(path).recheck(1, 10) == [request]
    completed = interval(10, 20)
    assert store.commit_history_complete(
        1, completed, [], exhausted=True, expected_version=version, verified_at=NOW
    )
    assert store.missing(1, request) == [interval(0, 10), interval(20, 30)]
    assert store.recheck(1, 10) == [interval(0, 10), interval(20, 30)]
    store.prune_before(NOW + timedelta(minutes=5))
    assert store.recheck(1, 10) == [interval(5, 10), interval(20, 30)]


def test_failed_history_record_rolls_back_coverage_and_messages(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watched = SQLiteWatchStore(path)
    version = watched.replace(1, frozenset({10}))
    store = SQLiteMessageStore(path)
    request = interval(0, 30)
    existing = MessageRecord(100, 2, 10, 3, "author", "elsewhere", NOW)
    store.upsert(existing, cached_at=NOW)
    collision = MessageRecord(100, 1, 10, 3, "author", "synthetic", NOW)
    with pytest.raises(MessageStoreError):
        store.commit_history_complete(
            1, request, [collision], exhausted=True, expected_version=version, verified_at=NOW
        )
    assert store.missing(1, request) == [request]
    assert store.recent(1, 10, NOW, NOW + timedelta(minutes=30)) == []


def test_gateway_startup_and_reconnect_require_history_recheck(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watched = SQLiteWatchStore(path)
        version = watched.replace(1, frozenset({10}))
        store = SQLiteMessageStore(path)
        settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"})
        current = [NOW]
        client = YoYackClient(
            watch_store=watched, message_store=store, settings=settings,
            clock=lambda: current[0],
        )
        client.tree = SimpleNamespace(sync=AsyncMock(return_value=[]))
        try:
            await client.setup_hook()
            initial = CoverageInterval(10, NOW - timedelta(days=30), NOW)
            assert store.recheck(1, 10) == [initial]
            assert store.commit_history_complete(
                1, initial, [], exhausted=True, expected_version=version, verified_at=NOW
            )
            assert store.recheck(1, 10) == []
            await client.on_disconnect()
            current[0] = NOW + timedelta(minutes=1)
            await client.on_resumed()
            assert store.recheck(1, 10) == [
                CoverageInterval(10, current[0] - timedelta(days=30), current[0])
            ]
        finally:
            await client.close()

    asyncio.run(scenario())
