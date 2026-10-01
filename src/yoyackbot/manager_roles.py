"""Per-server bot manager roles (1.1.3): who besides administrators may run slash commands."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from yoyackbot.channel_config import ConcurrentUpdate
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError


class ManagerRoleStore(Protocol):
    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]: ...

    def get(self, guild_id: int) -> frozenset[int]: ...

    def replace(
        self, guild_id: int, role_ids: frozenset[int], *, expected_version: int | None = None
    ) -> int: ...

    def remove_role(self, guild_id: int, role_id: int) -> bool: ...

    def remove_guild(self, guild_id: int) -> None: ...


class MemoryManagerRoleStore:
    def __init__(self) -> None:
        self._roles: dict[int, frozenset[int]] = {}
        self._versions: dict[int, int] = {}

    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]:
        return self._versions.get(guild_id, 0), self.get(guild_id)

    def get(self, guild_id: int) -> frozenset[int]:
        return self._roles.get(guild_id, frozenset())

    def replace(
        self, guild_id: int, role_ids: frozenset[int], *, expected_version: int | None = None
    ) -> int:
        version = self._versions.get(guild_id, 0)
        if expected_version is not None and expected_version != version:
            raise ConcurrentUpdate
        if self.get(guild_id) == role_ids:
            return version
        self._roles[guild_id] = frozenset(role_ids)
        self._versions[guild_id] = version + 1
        return version + 1

    def remove_role(self, guild_id: int, role_id: int) -> bool:
        if role_id not in self.get(guild_id):
            return False
        self.replace(guild_id, self.get(guild_id) - {role_id})
        return True

    def remove_guild(self, guild_id: int) -> None:
        self._roles.pop(guild_id, None)
        self._versions.pop(guild_id, None)


class SQLiteManagerRoleStore:
    """Optional tables next to the watched channels; the schema number stays 5."""

    def __init__(self, path: Path) -> None:
        self.path = path
        SQLiteWatchStore(path)  # creates or checks the schema-5 database and the optional tables

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA secure_delete=ON")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _version(connection: sqlite3.Connection, guild_id: int) -> int:
        row = connection.execute(
            "SELECT version FROM manager_role_meta WHERE guild_id=?", (guild_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]:
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN")
                return self._version(connection, guild_id), frozenset(
                    row[0] for row in connection.execute(
                        "SELECT role_id FROM manager_roles WHERE guild_id=?", (guild_id,)
                    )
                )
        except sqlite3.Error as exc:
            raise WatchStoreError("Manager role read failed") from exc

    def get(self, guild_id: int) -> frozenset[int]:
        return self.snapshot(guild_id)[1]

    def replace(
        self, guild_id: int, role_ids: frozenset[int], *, expected_version: int | None = None
    ) -> int:
        if guild_id < 1 or any(role_id < 1 for role_id in role_ids):
            raise ValueError("Guild and role identifiers must be positive")
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                version = self._version(connection, guild_id)
                if expected_version is not None and version != expected_version:
                    raise ConcurrentUpdate
                existing = frozenset(
                    row[0] for row in connection.execute(
                        "SELECT role_id FROM manager_roles WHERE guild_id=?", (guild_id,)
                    )
                )
                if existing == role_ids:
                    return version
                connection.execute("DELETE FROM manager_roles WHERE guild_id=?", (guild_id,))
                connection.executemany(
                    "INSERT INTO manager_roles(guild_id, role_id, updated_at) "
                    "VALUES (?, ?, unixepoch())",
                    ((guild_id, role_id) for role_id in sorted(role_ids)),
                )
                connection.execute(
                    "INSERT INTO manager_role_meta(guild_id, version) VALUES (?, 1) "
                    "ON CONFLICT(guild_id) DO UPDATE SET version=version+1", (guild_id,),
                )
                return version + 1
        except sqlite3.Error as exc:
            raise WatchStoreError("Manager role write failed") from exc

    def remove_role(self, guild_id: int, role_id: int) -> bool:
        current = self.get(guild_id)
        if role_id not in current:
            return False
        self.replace(guild_id, current - {role_id})
        return True

    def remove_guild(self, guild_id: int) -> None:
        try:
            with self._connection() as connection, connection:
                connection.execute("DELETE FROM manager_roles WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM manager_role_meta WHERE guild_id=?", (guild_id,))
        except sqlite3.Error as exc:
            raise WatchStoreError("Manager role cleanup failed") from exc
