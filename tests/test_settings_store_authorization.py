"""T120-P1-C: settings writes recheck authorization after acquiring the writer lock."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest

from yoyackbot.channel_config import ConcurrentUpdate
from yoyackbot.manager_roles import MemoryManagerRoleStore, SQLiteManagerRoleStore
from yoyackbot.watch_store import SQLiteWatchStore


@pytest.fixture(params=["memory_roles", "sqlite_roles", "sqlite_channels"])
def stores(request, tmp_path):
    if request.param == "memory_roles":
        roles = MemoryManagerRoleStore()
        store = roles
    else:
        path = tmp_path / "settings.db"
        roles = SQLiteManagerRoleStore(path)
        store = roles if request.param == "sqlite_roles" else SQLiteWatchStore(path)
    roles.replace(1, frozenset({11, 12}))
    roles.replace(2, frozenset({21}))
    if store is not roles:
        store.replace(1, frozenset({101}))
        store.replace(2, frozenset({201}))
    return store, roles


def test_guard_receives_current_guild_manager_roles_before_replacing(stores) -> None:
    store, roles = stores
    observed = []

    def authorize(current) -> bool:
        observed.append(current)
        return 11 in current

    assert store.replace(1, frozenset({31}), expected_version=1, authorize=authorize) == 2
    assert observed == [frozenset({11, 12})]
    assert store.snapshot(1) == (2, frozenset({31}))
    assert roles.get(2) == frozenset({21})


@pytest.mark.parametrize("unchanged", [False, True])
def test_denied_guard_preserves_settings_and_revision_even_for_no_op(stores, unchanged) -> None:
    store, _roles = stores
    original = store.snapshot(1)
    desired = original[1] if unchanged else frozenset()
    with pytest.raises(PermissionError, match="no longer authorized"):
        store.replace(1, desired, expected_version=original[0], authorize=lambda _roles: False)
    assert store.snapshot(1) == original


def test_guard_denial_precedes_stale_revision_and_guard_allow_keeps_cas(stores) -> None:
    store, _roles = stores
    original = store.snapshot(1)
    with pytest.raises(PermissionError):
        store.replace(1, frozenset(), expected_version=0, authorize=lambda _roles: False)
    with pytest.raises(ConcurrentUpdate):
        store.replace(1, frozenset(), expected_version=0, authorize=lambda _roles: True)
    assert store.snapshot(1) == original


def test_guard_exception_preserves_settings(stores) -> None:
    store, _roles = stores
    original = store.snapshot(1)

    def unavailable(_roles) -> bool:
        raise TimeoutError("synthetic authorization timeout")

    with pytest.raises(TimeoutError, match="synthetic authorization timeout"):
        store.replace(1, frozenset(), expected_version=1, authorize=unavailable)
    assert store.snapshot(1) == original


@pytest.mark.parametrize("kind", ["roles", "channels"])
def test_sqlite_guard_runs_after_writer_wait_and_observes_revocation(
    tmp_path, monkeypatch, kind,
) -> None:
    path = tmp_path / "settings.db"
    roles = SQLiteManagerRoleStore(path)
    roles.replace(1, frozenset({11, 12}))
    roles.replace(2, frozenset({11}))
    store = roles if kind == "roles" else SQLiteWatchStore(path)
    if kind == "channels":
        store.replace(1, frozenset({101}))
    original_connection = store._connection
    writer_waiting = Event()
    observed = []

    @contextmanager
    def traced_connection():
        with original_connection() as connection:
            connection.set_trace_callback(
                lambda statement: writer_waiting.set() if statement == "BEGIN IMMEDIATE" else None
            )
            yield connection

    def authorize(current) -> bool:
        observed.append(current)
        return 11 in current

    monkeypatch.setattr(store, "_connection", traced_connection)
    with sqlite3.connect(path) as competing, ThreadPoolExecutor(max_workers=1) as executor:
        competing.execute("BEGIN IMMEDIATE")
        future = executor.submit(
            store.replace, 1, frozenset({31}), expected_version=1, authorize=authorize,
        )
        try:
            assert writer_waiting.wait(timeout=2)
            assert observed == []  # No authorization against the stale pre-lock role set.
            competing.execute("DELETE FROM manager_roles WHERE guild_id=1 AND role_id=11")
            competing.execute("UPDATE manager_role_meta SET version=version+1 WHERE guild_id=1")
        finally:
            competing.commit()
        with pytest.raises(PermissionError, match="no longer authorized"):
            future.result(timeout=5)
    assert observed == [frozenset({12})]
    assert roles.snapshot(1) == (2, frozenset({12}))
    assert roles.get(2) == frozenset({11})
    if kind == "channels":
        assert store.snapshot(1) == (1, frozenset({101}))


@pytest.mark.parametrize("kind", ["roles", "channels"])
def test_sqlite_writer_lock_remains_held_while_authorizing(tmp_path, kind) -> None:
    path = tmp_path / "settings.db"
    roles = SQLiteManagerRoleStore(path)
    roles.replace(1, frozenset({11}))
    store = roles if kind == "roles" else SQLiteWatchStore(path)
    if kind == "channels":
        store.replace(1, frozenset({101}))

    def authorize(current) -> bool:
        assert current == frozenset({11})
        with sqlite3.connect(path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("BEGIN IMMEDIATE")
        return True

    assert store.replace(1, frozenset({31}), expected_version=1, authorize=authorize) == 2


def test_memory_role_store_holds_its_lock_while_authorizing() -> None:
    store = MemoryManagerRoleStore()
    store.replace(1, frozenset({11}))

    def authorize(current) -> bool:
        assert current == frozenset({11})
        assert store._lock.locked()
        return True

    assert store.replace(1, frozenset({31}), expected_version=1, authorize=authorize) == 2
