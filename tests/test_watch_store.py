"""Persistent watched-channel settings and transaction failure behavior."""

import sqlite3

import pytest

from yoyackbot.channel_config import ConcurrentUpdate
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError


def test_two_guilds_are_isolated_and_restore_after_restart(tmp_path) -> None:
    path = tmp_path / "private" / "settings.db"
    store = SQLiteWatchStore(path)
    assert store.get(1) == frozenset()
    assert store.version(1) == 0
    assert store.replace(1, frozenset({10, 11}), expected_version=0) == 1
    assert store.replace(2, frozenset({20}), expected_version=0) == 1
    restored = SQLiteWatchStore(path)
    assert restored.get(1) == frozenset({10, 11})
    assert restored.get(2) == frozenset({20})
    assert restored.replace(1, frozenset({11}), expected_version=1) == 2
    assert restored.get(2) == frozenset({20})
    assert path.stat().st_mode & 0o777 == 0o600


def test_stale_admin_selection_cannot_overwrite_newer_settings(tmp_path) -> None:
    path = tmp_path / "settings.db"
    first = SQLiteWatchStore(path)
    second = SQLiteWatchStore(path)
    initial = second.version(1)
    first.replace(1, frozenset({10}), expected_version=initial)
    with pytest.raises(ConcurrentUpdate):
        second.replace(1, frozenset({11}), expected_version=initial)
    assert first.get(1) == frozenset({10})


def test_insert_failure_rolls_back_previous_list(tmp_path) -> None:
    path = tmp_path / "settings.db"
    store = SQLiteWatchStore(path)
    store.replace(1, frozenset({10}))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_new_channel BEFORE INSERT ON watched_channels "
            "WHEN NEW.channel_id=11 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with pytest.raises(WatchStoreError):
        store.replace(1, frozenset({11}), expected_version=1)
    assert store.get(1) == frozenset({10})
    assert store.version(1) == 1


def test_channel_deletion_and_guild_leave_are_scoped(tmp_path) -> None:
    store = SQLiteWatchStore(tmp_path / "settings.db")
    store.replace(1, frozenset({10, 11}))
    store.replace(2, frozenset({20}))
    assert store.remove_channel(1, 10)
    assert not store.remove_channel(2, 10)
    assert store.get(1) == frozenset({11})
    assert store.version(1) == 2
    store.remove_guild(1)
    assert store.get(1) == frozenset()
    assert store.get(2) == frozenset({20})


def test_corrupt_database_read_fails_closed(tmp_path) -> None:
    path = tmp_path / "settings.db"
    store = SQLiteWatchStore(path)
    path.write_text("not a database")
    with pytest.raises(WatchStoreError):
        store.get(1)
