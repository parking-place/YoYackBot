"""Schema migration and exact indexed storage for Guild-scoped messages."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError

NOW = datetime(2026, 9, 28, 12, 34, 56, 123456, tzinfo=UTC)


def _record(message_id: int, *, guild_id: int = 1, channel_id: int = 10) -> MessageRecord:
    return MessageRecord(message_id, guild_id, channel_id, 3, "test author", "synthetic", NOW)


def test_new_database_keeps_settings_and_uses_current_schema(tmp_path) -> None:
    path = tmp_path / "private" / "messages.db"
    watched = SQLiteWatchStore(path)
    watched.replace(1, frozenset({10, 11}))
    watched.replace(2, frozenset({20}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    store.upsert(_record(100), cached_at=NOW)
    assert [item.message_id for item in store.recent(1, 10, NOW, NOW + timedelta(seconds=1))] == [100]
    assert store.recent(2, 10, NOW, NOW + timedelta(seconds=1)) == []
    assert SQLiteWatchStore(path).get(1) == frozenset({10, 11})
    assert SQLiteWatchStore(path).get(2) == frozenset({20})
    assert path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5


def test_version_one_migrates_forward_without_losing_existing_watch_state(tmp_path) -> None:
    path = tmp_path / "settings.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE guild_watch_meta (guild_id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE watched_channels (guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
            "updated_at INTEGER NOT NULL, PRIMARY KEY(guild_id, channel_id))"
        )
        connection.execute("INSERT INTO guild_watch_meta VALUES (1, 7)")
        connection.execute("INSERT INTO watched_channels VALUES (1, 10, 1)")
        connection.execute("PRAGMA user_version=1")
    assert SQLiteWatchStore(path).snapshot(1) == (7, frozenset({10}))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {
            "messages", "coverage", "coverage_recheck", "watched_channels",
            "summary_cooldowns",
        }


def test_version_two_migration_preserves_messages_and_verified_coverage(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watched = SQLiteWatchStore(path)
    watched.replace(1, frozenset({10}))
    messages = SQLiteMessageStore(path, clock=lambda: NOW)
    messages.upsert(_record(100), cached_at=NOW)
    interval = CoverageInterval(10, NOW, NOW + timedelta(hours=1))
    messages.mark_covered(1, interval, verified_at=NOW)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE coverage_recheck")
        connection.execute("DROP TABLE summary_cooldowns")
        connection.execute("ALTER TABLE messages DROP COLUMN has_attachment")
        connection.execute("ALTER TABLE messages DROP COLUMN is_reply")
        connection.execute("PRAGMA user_version=2")
    assert SQLiteWatchStore(path).get(1) == frozenset({10})
    assert [item.message_id for item in messages.recent(1, 10, NOW, NOW + timedelta(hours=1))] == [100]
    assert messages.coverage(1, 10) == [interval]
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5


def test_version_three_migration_preserves_messages_and_adds_context(tmp_path) -> None:
    path = tmp_path / "messages.db"
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    store.upsert(_record(100), cached_at=NOW)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE summary_cooldowns")
        connection.execute("ALTER TABLE messages DROP COLUMN has_attachment")
        connection.execute("ALTER TABLE messages DROP COLUMN is_reply")
        connection.execute("PRAGMA user_version=3")
    upgraded = SQLiteMessageStore(path, clock=lambda: NOW)
    assert upgraded.recent(1, 10, NOW, NOW + timedelta(seconds=1)) == [
        replace(_record(100), cached_at=NOW)
    ]
    updated = replace(_record(100), has_attachment=True, is_reply=True)
    upgraded.upsert(updated, cached_at=NOW)
    assert upgraded.recent(1, 10, NOW, NOW + timedelta(seconds=1)) == [
        replace(updated, cached_at=NOW + timedelta(microseconds=1))
    ]


def test_failed_migration_keeps_version_one_and_watch_settings(tmp_path) -> None:
    path = tmp_path / "settings.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE guild_watch_meta (guild_id INTEGER PRIMARY KEY, version INTEGER)")
        connection.execute(
            "CREATE TABLE watched_channels (guild_id INTEGER, channel_id INTEGER, updated_at INTEGER)"
        )
        connection.execute("INSERT INTO guild_watch_meta VALUES (1, 3)")
        connection.execute("INSERT INTO watched_channels VALUES (1, 10, 1)")
        connection.execute("CREATE TABLE messages (conflicting_schema TEXT)")
        connection.execute("PRAGMA user_version=1")
    with pytest.raises(WatchStoreError):
        SQLiteWatchStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT version FROM guild_watch_meta").fetchone()[0] == 3
        assert connection.execute("SELECT channel_id FROM watched_channels").fetchone()[0] == 10


def test_large_snowflakes_and_equal_timestamps_are_exactly_sorted_and_indexed(tmp_path) -> None:
    path = tmp_path / "messages.db"
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    high = 2**63 - 1
    store.upsert(_record(high), cached_at=NOW)
    store.upsert(_record(high - 1), cached_at=NOW)
    store.upsert(_record(10, guild_id=2), cached_at=NOW)
    store.upsert(_record(11, channel_id=11), cached_at=NOW)
    store.upsert(_record(12), cached_at=NOW)
    store.upsert(_record(12), cached_at=NOW + timedelta(seconds=1))
    result = store.recent(1, 10, NOW, NOW + timedelta(microseconds=1))
    assert [item.message_id for item in result] == [12, high - 1, high]
    assert result[0].created_at == NOW and result[0].cached_at == NOW + timedelta(seconds=1)
    assert store.recent(1, 10, NOW + timedelta(microseconds=1), NOW + timedelta(seconds=1)) == []

    with sqlite3.connect(path) as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT message_id FROM messages "
            "WHERE guild_id=? AND channel_id=? AND created_at_us>=? AND created_at_us<? "
            "ORDER BY created_at_us, message_id",
            (1, 10, 0, 2**63 - 1),
        ).fetchall()
    assert any("messages_guild_channel_time" in str(row) for row in plan)

    with pytest.raises(MessageStoreError):
        store.upsert(_record(high, guild_id=2), cached_at=NOW)
    assert len(store.recent(1, 10, NOW, NOW + timedelta(seconds=1))) == 3


def test_coverage_is_guild_scoped_and_removed_when_guild_leaves(tmp_path) -> None:
    path = tmp_path / "messages.db"
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    watched = SQLiteWatchStore(path)
    watched.replace(1, frozenset({10}))
    watched.replace(2, frozenset({10}))
    interval = CoverageInterval(10, NOW, NOW + timedelta(hours=1))
    store.mark_covered(1, interval, verified_at=NOW + timedelta(hours=1))
    store.mark_covered(2, interval, verified_at=NOW + timedelta(hours=1))
    store.upsert(_record(100), cached_at=NOW)
    assert store.coverage(1, 10) == [interval]
    watched.remove_guild(1)
    assert store.coverage(1, 10) == []
    assert store.coverage(2, 10) == [interval]
    assert store.recent(1, 10, NOW, NOW + timedelta(seconds=1)) == []


def test_watch_revision_and_cache_write_are_atomic_with_channel_removal(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watched = SQLiteWatchStore(path)
    first_version = watched.replace(1, frozenset({10}))
    watched.replace(2, frozenset({10}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    assert store.upsert_if_watched(_record(100), expected_version=first_version, cached_at=NOW)
    watched.replace(1, frozenset())
    assert not store.upsert_if_watched(
        _record(101), expected_version=first_version, cached_at=NOW
    )
    assert not store.upsert_if_watched(_record(102), expected_version=2, cached_at=NOW)
    assert store.recent(1, 10, NOW, NOW + timedelta(seconds=1)) == []
    assert store.upsert_if_watched(_record(103, guild_id=2), expected_version=1, cached_at=NOW)
    assert [item.message_id for item in store.recent(2, 10, NOW, NOW + timedelta(seconds=1))] == [103]


def test_retention_uses_creation_time_and_clips_coverage_at_exact_boundary(tmp_path) -> None:
    store = SQLiteMessageStore(tmp_path / "messages.db", clock=lambda: NOW)
    cutoff = NOW - timedelta(days=7)
    before = cutoff - timedelta(microseconds=1)
    after = cutoff + timedelta(microseconds=1)
    store.upsert(replace(_record(100), created_at=before), cached_at=NOW)
    store.upsert(replace(_record(101), created_at=cutoff), cached_at=NOW)
    store.upsert(replace(_record(102), created_at=after), cached_at=NOW)
    store.mark_covered(1, CoverageInterval(10, before, cutoff), verified_at=NOW)
    store.mark_covered(1, CoverageInterval(10, before, after), verified_at=NOW)
    assert store.prune_before(cutoff) == 1
    assert store.prune_before(cutoff) == 0
    assert [item.message_id for item in store.recent(1, 10, cutoff, NOW + timedelta(seconds=1))] == [101, 102]
    assert store.coverage(1, 10) == [CoverageInterval(10, cutoff, after)]


def test_raw_edit_updates_existing_only_and_deletion_is_scoped(tmp_path) -> None:
    store = SQLiteMessageStore(tmp_path / "messages.db", clock=lambda: NOW)
    SQLiteWatchStore(store.path).replace(1, frozenset({10}))
    store.upsert(_record(100), cached_at=NOW)
    store.upsert(_record(101, guild_id=2), cached_at=NOW)
    assert store.update_content(
        1, 10, 100, "edited synthetic", edited_at=NOW + timedelta(seconds=1),
        cached_at=NOW + timedelta(seconds=2),
    )
    assert not store.update_content(
        1, 10, 999, "unknown", edited_at=NOW, cached_at=NOW,
    )
    edited = store.recent(1, 10, NOW, NOW + timedelta(seconds=1))[0]
    assert edited.content == "edited synthetic"
    assert edited.edited_at == NOW + timedelta(seconds=1)
    assert store.delete_many(1, 10, {100, 101, 999}) == 1
    assert store.delete_many(1, 10, {100}) == 0
    assert store.recent(1, 10, NOW, NOW + timedelta(seconds=1)) == []
    assert [item.message_id for item in store.recent(2, 10, NOW, NOW + timedelta(seconds=1))] == [101]
