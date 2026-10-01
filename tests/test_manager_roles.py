"""Per-server bot manager roles: storage, schema, backups, operator command, cleanup (T113-P1)."""

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoyackbot.__main__ import main
from yoyackbot.channel_config import ConcurrentUpdate
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.manager_roles import MemoryManagerRoleStore, SQLiteManagerRoleStore
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.settings_backup import backup_settings, restore_settings
from yoyackbot.watch_store import SQLiteWatchStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path: Path):
    return MemoryManagerRoleStore() if request.param == "memory" else SQLiteManagerRoleStore(tmp_path / "db")


def test_store_keeps_servers_apart_and_detects_concurrent_edits(store) -> None:
    assert store.snapshot(1) == (0, frozenset())
    assert store.replace(1, frozenset({11, 12})) == 1
    assert store.replace(2, frozenset({21})) == 1
    assert store.replace(1, frozenset({11, 12})) == 1  # unchanged keeps the version
    version, _roles = store.snapshot(1)
    with pytest.raises(ConcurrentUpdate):
        store.replace(1, frozenset({11}), expected_version=version - 1)
    assert store.replace(1, frozenset({11}), expected_version=version) == 2
    assert store.remove_role(1, 11) and not store.remove_role(1, 11)
    assert store.get(1) == frozenset() and store.get(2) == frozenset({21})
    store.remove_guild(2)
    assert store.snapshot(2) == (0, frozenset())


def test_sqlite_rejects_bad_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SQLiteManagerRoleStore(tmp_path / "db").replace(1, frozenset({0}))


def test_schema_stays_five_and_old_databases_gain_the_optional_tables(tmp_path: Path) -> None:
    path = tmp_path / "db"
    SQLiteWatchStore(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE manager_roles")
        connection.execute("DROP TABLE manager_role_meta")
    SQLiteManagerRoleStore(path).replace(1, frozenset({5}))
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT guild_id, role_id FROM manager_roles").fetchall() == [(1, 5)]


def test_settings_backup_carries_manager_roles_and_reads_older_backups(tmp_path: Path) -> None:
    live = tmp_path / "live.db"
    SQLiteWatchStore(live).replace(1, frozenset({10}))
    SQLiteManagerRoleStore(live).replace(1, frozenset({55, 56}))
    backup = backup_settings(live, tmp_path / "backups")
    data = json.loads(backup.read_text())
    assert [row[:2] for row in data["manager_roles"]] == [[1, 55], [1, 56]]
    restored = tmp_path / "restored.db"
    restore_settings(backup, restored, live_database=live)
    assert SQLiteManagerRoleStore(restored).snapshot(1) == (1, frozenset({55, 56}))

    older = tmp_path / "backups" / "older.json"
    del data["manager_meta"], data["manager_roles"]
    older.write_text(json.dumps(data))
    older.chmod(0o600)
    again = tmp_path / "again.db"
    restore_settings(older, again, live_database=live)
    assert SQLiteManagerRoleStore(again).get(1) == frozenset()
    assert SQLiteWatchStore(again).get(1) == frozenset({10})


def run_cli(monkeypatch, capsys, tmp_path: Path, *words: str) -> tuple[int, str]:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic")
    monkeypatch.setenv("YOYACK_DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setattr(sys, "argv", ["yoyackbot", "manager-roles", *words])
    code = main()
    return code, capsys.readouterr().out.strip()


def test_operator_command_lists_sets_and_clears(monkeypatch, capsys, tmp_path: Path) -> None:
    assert run_cli(monkeypatch, capsys, tmp_path, "list", "7") == (0, "Manager roles: 0")
    assert run_cli(monkeypatch, capsys, tmp_path, "set", "7", "300", "200") == (0, "Manager roles: 2: 200 300")
    assert run_cli(monkeypatch, capsys, tmp_path, "list", "7") == (0, "Manager roles: 2: 200 300")
    assert run_cli(monkeypatch, capsys, tmp_path, "clear", "7") == (0, "Manager roles: 0")
    for bad in (("set", "7"), ("list", "x"), ("drop", "7"), ("list",), ("clear", "7", "1"), ("set", "0", "1")):
        code, out = run_cli(monkeypatch, capsys, tmp_path, *bad)
        assert code == 2 and out.startswith("Usage: manager-roles"), bad


def test_client_cleans_up_on_server_leave_and_role_delete(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "db"
        client = YoYackClient(
            watch_store=SQLiteWatchStore(path), message_store=SQLiteMessageStore(path),
            settings=Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_DB_PATH": str(path)}),
            clock=lambda: datetime(2026, 10, 1, tzinfo=UTC),
        )
        try:
            assert isinstance(client.manager_roles, SQLiteManagerRoleStore)
            client.manager_roles.replace(1, frozenset({55, 56}))
            await client.on_guild_role_delete(SimpleNamespace(id=55, guild=SimpleNamespace(id=1)))
            assert client.manager_roles.get(1) == frozenset({56})
            await client.on_guild_remove(SimpleNamespace(id=1))
            assert client.manager_roles.snapshot(1) == (0, frozenset())
        finally:
            await client.close()

    asyncio.run(scenario())
