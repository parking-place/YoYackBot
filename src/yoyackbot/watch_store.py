"""SQLite watched-channel settings, isolated by Guild and updated atomically."""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import discord

from yoyackbot.backfill_state import start_progress
from yoyackbot.channel_config import ConcurrentUpdate

_RETENTION_US = 30 * 24 * 60 * 60 * 1_000_000


def _new_backfill(guild_id: int, channel_id: int, *, first_watch: bool) -> tuple:
    started_us = time.time_ns() // 1_000
    before_id = discord.utils.time_snowflake(
        datetime.fromtimestamp(started_us / 1_000_000, UTC), high=True
    ) + 1
    return (
        guild_id, channel_id, secrets.token_hex(16), int(first_watch),
        started_us, started_us - _RETENTION_US, before_id,
    )


def insert_backfills(connection: sqlite3.Connection, rows: Iterable[tuple]) -> None:
    """Create initial collection runs and start counting their pages in one transaction."""
    for row in rows:
        connection.execute(
            "INSERT INTO backfill_state (guild_id, channel_id, token, first_watch, started_us, "
            "cutoff_us, before_id) VALUES (?, ?, ?, ?, ?, ?, ?)", row,
        )
        guild_id, channel_id, token, _first, started_us, _cutoff, before_id = row
        start_progress(
            connection, guild_id, channel_id, token=token, started_us=started_us,
            kind="initial", cursor=before_id,
        )


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
                if version > 5:
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
                if version in (0, 1):
                    with connection:
                        connection.execute(
                            "CREATE TABLE messages ("
                            "message_id INTEGER PRIMARY KEY CHECK(message_id > 0), "
                            "guild_id INTEGER NOT NULL CHECK(guild_id > 0), "
                            "channel_id INTEGER NOT NULL CHECK(channel_id > 0), "
                            "author_id INTEGER NOT NULL CHECK(author_id > 0), "
                            "author_name TEXT NOT NULL, content TEXT NOT NULL, "
                            "created_at_us INTEGER NOT NULL, edited_at_us INTEGER, "
                            "cached_at_us INTEGER NOT NULL)"
                        )
                        connection.execute(
                            "CREATE INDEX messages_guild_channel_time "
                            "ON messages(guild_id, channel_id, created_at_us, message_id)"
                        )
                        connection.execute(
                            "CREATE TABLE coverage ("
                            "guild_id INTEGER NOT NULL CHECK(guild_id > 0), "
                            "channel_id INTEGER NOT NULL CHECK(channel_id > 0), "
                            "start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, "
                            "verified_at_us INTEGER NOT NULL, CHECK(start_us < end_us), "
                            "PRIMARY KEY(guild_id, channel_id, start_us, end_us))"
                        )
                        connection.execute("PRAGMA user_version=2")
                if version in (0, 1, 2):
                    with connection:
                        connection.execute(
                            "CREATE TABLE coverage_recheck ("
                            "guild_id INTEGER NOT NULL CHECK(guild_id > 0), "
                            "channel_id INTEGER NOT NULL CHECK(channel_id > 0), "
                            "start_us INTEGER NOT NULL, end_us INTEGER NOT NULL, "
                            "reason TEXT NOT NULL, CHECK(start_us < end_us), "
                            "PRIMARY KEY(guild_id, channel_id, start_us, end_us))"
                        )
                        connection.execute("PRAGMA user_version=3")
                if version in (0, 1, 2, 3):
                    with connection:
                        connection.execute(
                            "ALTER TABLE messages ADD COLUMN has_attachment INTEGER NOT NULL DEFAULT 0"
                        )
                        connection.execute(
                            "ALTER TABLE messages ADD COLUMN is_reply INTEGER NOT NULL DEFAULT 0"
                        )
                        connection.execute("PRAGMA user_version=4")
                if version in (0, 1, 2, 3, 4):
                    with connection:
                        connection.execute(
                            "CREATE TABLE summary_cooldowns ("
                            "guild_id INTEGER NOT NULL CHECK(guild_id > 0), "
                            "channel_id INTEGER NOT NULL CHECK(channel_id > 0), "
                            "last_success_us INTEGER NOT NULL, "
                            "expires_at_us INTEGER NOT NULL, "
                            "PRIMARY KEY(guild_id, channel_id), "
                            "CHECK(expires_at_us >= last_success_us))"
                        )
                        connection.execute("PRAGMA user_version=5")
                # Optional to schema 5 so the released 1.0.0a reader can be restored.
                with connection:
                    # A single logical observation clock survives deletion of the newest row.
                    # It carries no message/channel data and is excluded from settings backups.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS cache_observation_clock ("
                        "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                        "last_us INTEGER NOT NULL)"
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS messages_guild_channel_observed "
                        "ON messages(guild_id, channel_id, cached_at_us)"
                    )
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS backfill_state ("
                        "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
                        "token TEXT NOT NULL, first_watch INTEGER NOT NULL, "
                        "started_us INTEGER NOT NULL, cutoff_us INTEGER NOT NULL, "
                        "before_id INTEGER NOT NULL, phase TEXT NOT NULL DEFAULT 'history', "
                        "finished_us INTEGER, overlap_start_us INTEGER, "
                        "overlap_before_id INTEGER, "
                        "verified_us INTEGER, retry_at_us INTEGER NOT NULL DEFAULT 0, "
                        "started_notice_id INTEGER, ready_notice_id INTEGER, "
                        "started_notice_attempt_us INTEGER, ready_notice_attempt_us INTEGER, "
                        "blocked_reason TEXT, "
                        "PRIMARY KEY(guild_id, channel_id))"
                    )
                    columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(backfill_state)")
                    }
                    if "overlap_start_us" not in columns:
                        connection.execute(
                            "ALTER TABLE backfill_state ADD COLUMN overlap_start_us INTEGER"
                        )
                    if "started_notice_attempt_us" not in columns:
                        connection.execute(
                            "ALTER TABLE backfill_state ADD COLUMN started_notice_attempt_us INTEGER"
                        )
                    if "ready_notice_attempt_us" not in columns:
                        connection.execute(
                            "ALTER TABLE backfill_state ADD COLUMN ready_notice_attempt_us INTEGER"
                        )
                    if "blocked_reason" not in columns:
                        connection.execute(
                            "ALTER TABLE backfill_state ADD COLUMN blocked_reason TEXT"
                        )
                    # 1.1.3: per-server bot manager roles, optional so schema 5 readers still work.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS manager_role_meta ("
                        "guild_id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
                    )
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS manager_roles ("
                        "guild_id INTEGER NOT NULL, role_id INTEGER NOT NULL, "
                        "updated_at INTEGER NOT NULL, PRIMARY KEY(guild_id, role_id))"
                    )
                    # 1.2.0 F02: per-run page progress. Counts and times only; never backed up.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS backfill_progress ("
                        "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
                        "token TEXT NOT NULL, run_started_us INTEGER NOT NULL, "
                        "kind TEXT NOT NULL, pages INTEGER, last_cursor INTEGER NOT NULL, "
                        "last_progress_us INTEGER, PRIMARY KEY(guild_id, channel_id))"
                    )
                    # An older release may have unwatched channels without knowing this table.
                    connection.execute(
                        "DELETE FROM backfill_progress WHERE NOT EXISTS (SELECT 1 FROM "
                        "backfill_state b WHERE b.guild_id=backfill_progress.guild_id "
                        "AND b.channel_id=backfill_progress.channel_id "
                        "AND b.token=backfill_progress.token)"
                    )
                    # 1.2.0 F10: reply links (IDs only). The trigger also runs for older
                    # releases' deletes, so a removed message never leaves a link behind.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS message_reply_refs ("
                        "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
                        "message_id INTEGER NOT NULL, target_id INTEGER NOT NULL, "
                        "observed_us INTEGER NOT NULL, "
                        "PRIMARY KEY(guild_id, channel_id, message_id), "
                        "CHECK(0 < target_id AND target_id < message_id))"
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS message_reply_refs_target "
                        "ON message_reply_refs(guild_id, channel_id, target_id)"
                    )
                    connection.execute(
                        "CREATE TRIGGER IF NOT EXISTS message_reply_refs_cleanup "
                        "AFTER DELETE ON messages BEGIN "
                        "DELETE FROM message_reply_refs WHERE guild_id=OLD.guild_id "
                        "AND channel_id=OLD.channel_id "
                        "AND (message_id=OLD.message_id OR target_id=OLD.message_id); END"
                    )
                    # Links whose message is gone (written before the trigger existed).
                    connection.execute(
                        "DELETE FROM message_reply_refs WHERE NOT EXISTS (SELECT 1 FROM messages m "
                        "WHERE m.message_id=message_reply_refs.message_id "
                        "AND m.guild_id=message_reply_refs.guild_id "
                        "AND m.channel_id=message_reply_refs.channel_id)"
                    )
                    # 1.3.0 `/말투`: a server's tone text (NULL = default). Backed up as a setting.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS guild_tones ("
                        "guild_id INTEGER PRIMARY KEY CHECK(guild_id > 0), content TEXT, "
                        "version INTEGER NOT NULL, updated_us INTEGER NOT NULL)"
                    )
                    # 1.3.0: the last posted ratings per channel (model text only), not backed up.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS recent_ratings ("
                        "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
                        "posted_us INTEGER NOT NULL, text TEXT NOT NULL)"
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS recent_ratings_channel "
                        "ON recent_ratings(guild_id, channel_id, posted_us)"
                    )
                    # An older release may unwatch or leave without knowing this table.
                    connection.execute(
                        "DELETE FROM recent_ratings WHERE NOT EXISTS (SELECT 1 FROM watched_channels w "
                        "WHERE w.guild_id=recent_ratings.guild_id "
                        "AND w.channel_id=recent_ratings.channel_id)"
                    )
                    # 1.3.1: `!!말하자면` success cooldowns, counted apart from summaries.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS idiom_cooldowns ("
                        "guild_id INTEGER NOT NULL CHECK(guild_id > 0), "
                        "channel_id INTEGER NOT NULL CHECK(channel_id > 0), "
                        "last_success_us INTEGER NOT NULL, "
                        "expires_at_us INTEGER NOT NULL, "
                        "PRIMARY KEY(guild_id, channel_id), "
                        "CHECK(expires_at_us >= last_success_us))"
                    )
                    connection.execute(
                        "DELETE FROM idiom_cooldowns WHERE NOT EXISTS (SELECT 1 FROM watched_channels w "
                        "WHERE w.guild_id=idiom_cooldowns.guild_id "
                        "AND w.channel_id=idiom_cooldowns.channel_id)"
                    )
                    # 1.3.1 `/속도 설정`: a row means the server turned the fast tier on.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS guild_fast_mode ("
                        "guild_id INTEGER PRIMARY KEY CHECK(guild_id > 0), "
                        "updated_us INTEGER NOT NULL)"
                    )
                    # 1.4.0 처형: one log channel per server and the roles allowed to use /처형.
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS execution_settings ("
                        "guild_id INTEGER PRIMARY KEY CHECK(guild_id > 0), "
                        "channel_id INTEGER NOT NULL CHECK(channel_id > 0), "
                        "updated_us INTEGER NOT NULL)"
                    )
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS execution_roles ("
                        "guild_id INTEGER NOT NULL CHECK(guild_id > 0), "
                        "role_id INTEGER NOT NULL CHECK(role_id > 0), "
                        "updated_us INTEGER NOT NULL, PRIMARY KEY(guild_id, role_id))"
                    )
                    connection.execute(
                        "CREATE TABLE IF NOT EXISTS deleted_messages ("
                        "guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
                        "message_id INTEGER NOT NULL, deleted_at_us INTEGER NOT NULL, "
                        "PRIMARY KEY(guild_id, channel_id, message_id))"
                    )
        except (OSError, sqlite3.Error) as exc:
            raise WatchStoreError("Settings database unavailable") from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
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
        self, guild_id: int, channel_ids: frozenset[int], *, expected_version: int | None = None,
        authorize: Callable[[frozenset[int] | None], bool] | None = None,
    ) -> int:
        if guild_id < 1 or any(channel_id < 1 for channel_id in channel_ids):
            raise ValueError("Guild and channel identifiers must be positive")
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                if authorize is not None:
                    manager_roles = frozenset(
                        row[0] for row in connection.execute(
                            "SELECT role_id FROM manager_roles WHERE guild_id=?", (guild_id,)
                        )
                    )
                    if not authorize(manager_roles):
                        raise PermissionError("Channel update is no longer authorized")
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
                for removed_id in existing - channel_ids:
                    connection.execute(
                        "DELETE FROM deleted_messages WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM backfill_state WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM backfill_progress WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM message_reply_refs WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM recent_ratings WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM summary_cooldowns WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM idiom_cooldowns WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM messages WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM coverage WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                    connection.execute(
                        "DELETE FROM coverage_recheck WHERE guild_id=? AND channel_id=?",
                        (guild_id, removed_id),
                    )
                insert_backfills(connection, (
                    _new_backfill(guild_id, channel_id, first_watch=True)
                    for channel_id in sorted(channel_ids - existing)
                ))
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
                        "DELETE FROM deleted_messages WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM backfill_state WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM backfill_progress WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM message_reply_refs WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM recent_ratings WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM summary_cooldowns WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM idiom_cooldowns WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM messages WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM coverage WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
                    connection.execute(
                        "DELETE FROM coverage_recheck WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
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
                connection.execute("DELETE FROM messages WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM coverage WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM coverage_recheck WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM summary_cooldowns WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM idiom_cooldowns WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM deleted_messages WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM backfill_state WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM backfill_progress WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM message_reply_refs WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM recent_ratings WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM guild_tones WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM guild_fast_mode WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM execution_settings WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM execution_roles WHERE guild_id=?", (guild_id,))
                connection.execute("DELETE FROM guild_watch_meta WHERE guild_id=?", (guild_id,))
        except sqlite3.Error as exc:
            raise WatchStoreError("Settings Guild removal failed") from exc
