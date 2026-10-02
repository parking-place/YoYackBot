"""T120-P1-B: deleted-role cleanup cannot overwrite another administrator's edit."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier

import pytest

from yoyackbot.channel_config import ConcurrentUpdate
from yoyackbot.manager_roles import MemoryManagerRoleStore, SQLiteManagerRoleStore
from yoyackbot.watch_store import WatchStoreError


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    if request.param == "memory":
        return MemoryManagerRoleStore()
    return SQLiteManagerRoleStore(tmp_path / "roles.db")


@pytest.mark.parametrize("operation", ["add", "remove", "clear"])
def test_sqlite_deleted_role_preserves_an_interleaved_administrator_edit(
    tmp_path: Path, monkeypatch, operation: str,
) -> None:
    path = tmp_path / "roles.db"
    deletion = SQLiteManagerRoleStore(path)
    administrator = SQLiteManagerRoleStore(path)
    deletion.replace(1, frozenset({11, 12, 13}))
    deletion.replace(2, frozenset({21}))
    original_connection = deletion._connection
    interleaved = False

    @contextmanager
    def connection_with_interleaved_edit():
        nonlocal interleaved
        with original_connection() as connection:
            yield connection
        if not interleaved:
            interleaved = True
            # With the old get/replace cleanup, this is after the stale read
            # and before its write. An atomic cleanup has already committed,
            # so the same edit is serialized after the deletion instead.
            version, current = administrator.snapshot(1)
            updated = {
                "add": current | {14},
                "remove": current - {12},
                "clear": frozenset(),
            }[operation]
            administrator.replace(1, updated, expected_version=version)

    monkeypatch.setattr(deletion, "_connection", connection_with_interleaved_edit)
    assert deletion.remove_role(1, 11)
    assert interleaved
    expected = {
        "add": frozenset({12, 13, 14}),
        "remove": frozenset({13}),
        "clear": frozenset(),
    }[operation]
    assert administrator.snapshot(1) == (3, expected)
    assert administrator.snapshot(2) == (1, frozenset({21}))


def test_deletion_advances_revision_and_rejects_a_stale_draft(store) -> None:
    version = store.replace(1, frozenset({11, 12}))
    assert store.remove_role(1, 11)
    assert store.snapshot(1) == (version + 1, frozenset({12}))
    for stale_draft in (frozenset({11, 12, 13}), frozenset({12})):
        with pytest.raises(ConcurrentUpdate):
            store.replace(1, stale_draft, expected_version=version)
    assert store.snapshot(1) == (version + 1, frozenset({12}))
    assert not store.remove_role(1, 11)
    assert store.snapshot(1) == (version + 1, frozenset({12}))
    assert not store.remove_role(2, 11)
    assert store.snapshot(2) == (0, frozenset())


def test_duplicate_concurrent_deletions_advance_revision_only_once(store) -> None:
    store.replace(1, frozenset({11, 12}))
    store.replace(2, frozenset({21}))
    start = Barrier(2)

    def delete() -> bool:
        start.wait(timeout=5)
        return store.remove_role(1, 11)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(delete)
        second = executor.submit(delete)
        assert sorted([first.result(timeout=10), second.result(timeout=10)]) == [False, True]
    assert store.snapshot(1) == (2, frozenset({12}))
    assert store.snapshot(2) == (1, frozenset({21}))


def test_sqlite_revision_failure_rolls_back_the_role_deletion(tmp_path: Path) -> None:
    path = tmp_path / "roles.db"
    store = SQLiteManagerRoleStore(path)
    original = frozenset({11, 12})
    store.replace(1, original)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_role_revision BEFORE UPDATE ON manager_role_meta "
            "BEGIN SELECT RAISE(ABORT, 'synthetic revision failure'); END"
        )

    with pytest.raises(WatchStoreError, match="Manager role cleanup failed"):
        store.remove_role(1, 11)
    assert store.snapshot(1) == (1, original)


@pytest.mark.parametrize(("guild_id", "role_id"), [(0, 11), (1, 0), (-1, 11), (1, -1)])
def test_deleted_role_rejects_invalid_identifiers(store, guild_id: int, role_id: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        store.remove_role(guild_id, role_id)
