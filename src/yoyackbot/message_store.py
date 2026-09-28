"""Guild-scoped SQLite message and coverage storage on schema version two."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.watch_store import SQLiteWatchStore

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class MessageStoreError(RuntimeError):
    """Message or coverage data could not be stored safely."""


def _microseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamps must have a timezone")
    delta = value.astimezone(UTC) - EPOCH
    return ((delta.days * 86400 + delta.seconds) * 1_000_000) + delta.microseconds


def _datetime(value: int) -> datetime:
    return EPOCH + timedelta(microseconds=value)


class SQLiteMessageStore:
    def __init__(self, path: Path) -> None:
        SQLiteWatchStore(path)
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _upsert(connection: sqlite3.Connection, record: MessageRecord, cached_at: datetime) -> None:
        if min(record.message_id, record.guild_id, record.channel_id, record.author_id) < 1:
            raise ValueError("message identifiers must be positive")
        values = (
            record.message_id,
            record.guild_id,
            record.channel_id,
            record.author_id,
            record.author_name,
            record.content,
            _microseconds(record.created_at),
            _microseconds(record.edited_at) if record.edited_at is not None else None,
            _microseconds(cached_at),
        )
        cursor = connection.execute(
            "INSERT INTO messages (message_id, guild_id, channel_id, author_id, "
            "author_name, content, created_at_us, edited_at_us, cached_at_us) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET author_id=excluded.author_id, "
            "author_name=excluded.author_name, content=excluded.content, "
            "edited_at_us=excluded.edited_at_us, cached_at_us=excluded.cached_at_us "
            "WHERE messages.guild_id=excluded.guild_id "
            "AND messages.channel_id=excluded.channel_id",
            values,
        )
        if cursor.rowcount != 1:
            raise MessageStoreError("Message ID belongs to another channel")

    def upsert(self, record: MessageRecord, *, cached_at: datetime) -> None:
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._upsert(connection, record, cached_at)
        except sqlite3.Error as exc:
            raise MessageStoreError("Message write failed") from exc

    def upsert_if_watched(
        self, record: MessageRecord, *, expected_version: int, cached_at: datetime
    ) -> bool:
        """Serialize watch revision check and write against concurrent removal."""
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute(
                    "SELECT version FROM guild_watch_meta WHERE guild_id=?", (record.guild_id,)
                ).fetchone()
                if version is None or version[0] != expected_version:
                    return False
                watched = connection.execute(
                    "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
                    (record.guild_id, record.channel_id),
                ).fetchone()
                if watched is None:
                    return False
                self._upsert(connection, record, cached_at)
                return True
        except sqlite3.Error as exc:
            raise MessageStoreError("Watched message write failed") from exc

    def recent(
        self, guild_id: int, channel_id: int, start: datetime, end: datetime
    ) -> Sequence[MessageRecord]:
        start_us, end_us = _microseconds(start), _microseconds(end)
        if start_us > end_us:
            raise ValueError("start must not follow end")
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT message_id, guild_id, channel_id, author_id, author_name, content, "
                    "created_at_us, edited_at_us, cached_at_us FROM messages "
                    "WHERE guild_id=? AND channel_id=? AND created_at_us>=? AND created_at_us<? "
                    "ORDER BY created_at_us, message_id",
                    (guild_id, channel_id, start_us, end_us),
                ).fetchall()
        except sqlite3.Error as exc:
            raise MessageStoreError("Message read failed") from exc
        return [
            MessageRecord(
                message_id=row[0],
                guild_id=row[1],
                channel_id=row[2],
                author_id=row[3],
                author_name=row[4],
                content=row[5],
                created_at=_datetime(row[6]),
                edited_at=_datetime(row[7]) if row[7] is not None else None,
                cached_at=_datetime(row[8]),
            )
            for row in rows
        ]

    def mark_covered(
        self, guild_id: int, interval: CoverageInterval, *, verified_at: datetime
    ) -> None:
        if guild_id < 1 or interval.channel_id < 1:
            raise ValueError("Guild and channel identifiers must be positive")
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO coverage "
                    "(guild_id, channel_id, start_us, end_us, verified_at_us) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(guild_id, channel_id, start_us, end_us) "
                    "DO UPDATE SET verified_at_us=excluded.verified_at_us",
                    (
                        guild_id,
                        interval.channel_id,
                        _microseconds(interval.start),
                        _microseconds(interval.end),
                        _microseconds(verified_at),
                    ),
                )
        except sqlite3.Error as exc:
            raise MessageStoreError("Coverage write failed") from exc

    def coverage(self, guild_id: int, channel_id: int) -> Sequence[CoverageInterval]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT start_us, end_us FROM coverage "
                    "WHERE guild_id=? AND channel_id=? ORDER BY start_us, end_us",
                    (guild_id, channel_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise MessageStoreError("Coverage read failed") from exc
        return [CoverageInterval(channel_id, _datetime(start), _datetime(end)) for start, end in rows]
