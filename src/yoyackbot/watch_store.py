"""SQLite watched-channel settings, isolated by Guild and updated atomically."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from yoyackbot.channel_config import ConcurrentUpdate


class WatchStoreError(RuntimeError):
    """Settings could not be read or changed safely."""


class SQLiteWatchStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not path.exists():
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            os.chmod(path, 0o600)
            with self._connection() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > 1:
                    raise WatchStoreError("Unsupported settings schema version")
                if version == 0:
                    with connection:
                        connection.execute(
                            "CREATE TABLE guild_watch_meta ("
                            "guild_id INTEGER PRIMARY KEY CHECK(guild_id > 0), "
                            "version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0))"
                        )
                        connection.execute(
                            "CREATE TABLE watched_channels ("
                            "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL "
                            "CHECK(channel_id > 0), updated_at INTEGER NOT NULL, "
                            "PRIMARY KEY(guild_id, channel_id), "
                            "FOREIGN KEY(guild_id) REFERENCES guild_watch_meta(guild_id) "
                            "ON DELETE CASCADE)"
                        )
                        connection.execute("PRAGMA user_version=1")
        except (OSError, sqlite3.Error) as exc:
            raise WatchStoreError("Settings database unavailable") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _version(connection: sqlite3.Connection, guild_id: int) -> int:
        row = connection.execute(
            "SELECT version FROM guild_watch_meta WHERE guild_id=?", (guild_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def version(self, guild_id: int) -> int:
        return self.snapshot(guild_id)[0]

    def get(self, guild_id: int) -> frozenset[int]:
        return self.snapshot(guild_id)[1]

    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]:
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN")
                version = self._version(connection, guild_id)
                channels = frozenset(
                    row[0]
                    for row in connection.execute(
                        "SELECT channel_id FROM watched_channels WHERE guild_id=?", (guild_id,)
                    )
                )
                return version, channels
        except sqlite3.Error as exc:
            raise WatchStoreError("Settings read failed") from exc

    def replace(
        self, guild_id: int, channel_ids: frozenset[int], *, expected_version: int | None = None
    ) -> int:
        if guild_id < 1 or any(channel_id < 1 for channel_id in channel_ids):
            raise ValueError("Guild and channel identifiers must be positive")
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                version = self._version(connection, guild_id)
                if expected_version is not None and version != expected_version:
                    raise ConcurrentUpdate
                existing = frozenset(
                    row[0]
                    for row in connection.execute(
                        "SELECT channel_id FROM watched_channels WHERE guild_id=?", (guild_id,)
                    )
                )
                if existing == channel_ids:
                    return version
                connection.execute(
                    "INSERT OR IGNORE INTO guild_watch_meta(guild_id, version) VALUES (?, 0)",
                    (guild_id,),
                )
                connection.execute("DELETE FROM watched_channels WHERE guild_id=?", (guild_id,))
                connection.executemany(
                    "INSERT INTO watched_channels(guild_id, channel_id, updated_at) "
                    "VALUES (?, ?, unixepoch())",
                    ((guild_id, channel_id) for channel_id in sorted(channel_ids)),
                )
                connection.execute(
                    "UPDATE guild_watch_meta SET version=version+1 WHERE guild_id=?", (guild_id,)
                )
                return version + 1
        except sqlite3.Error as exc:
            raise WatchStoreError("Settings write failed") from exc

    def remove_channel(self, guild_id: int, channel_id: int) -> bool:
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM watched_channels WHERE guild_id=? AND channel_id=?",
                    (guild_id, channel_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        "UPDATE guild_watch_meta SET version=version+1 WHERE guild_id=?", (guild_id,)
                    )
                return bool(cursor.rowcount)
        except sqlite3.Error as exc:
            raise WatchStoreError("Settings channel removal failed") from exc

    def remove_guild(self, guild_id: int) -> None:
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM guild_watch_meta WHERE guild_id=?", (guild_id,))
        except sqlite3.Error as exc:
            raise WatchStoreError("Settings Guild removal failed") from exc
