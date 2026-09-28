"""Guild-scoped SQLite message and coverage storage on schema version two."""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

from yoyackbot.coverage import missing_intervals
from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.watch_store import SQLiteWatchStore

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class CacheFailureKind(Enum):
    LOCKED = "locked"
    READ_ONLY = "read_only"
    FULL = "full"
    CORRUPT = "corrupt"
    OTHER = "other"


class MessageStoreError(RuntimeError):
    """Safe diagnostic category for cache fallback decisions."""

    def __init__(self, message: str, *, kind: CacheFailureKind = CacheFailureKind.OTHER) -> None:
        super().__init__(message)
        self.kind = kind


def _store_error(message: str, error: sqlite3.Error) -> MessageStoreError:
    code = getattr(error, "sqlite_errorcode", None)
    primary = code & 0xFF if isinstance(code, int) else None
    if primary in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        kind = CacheFailureKind.LOCKED
    elif primary in {sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM}:
        kind = CacheFailureKind.READ_ONLY
    elif primary == sqlite3.SQLITE_FULL:
        kind = CacheFailureKind.FULL
    elif primary in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        kind = CacheFailureKind.CORRUPT
    else:
        kind = CacheFailureKind.OTHER
    return MessageStoreError(message, kind=kind)


def _microseconds(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("timestamps must have a timezone")
    delta = value.astimezone(UTC) - EPOCH
    return ((delta.days * 86400 + delta.seconds) * 1_000_000) + delta.microseconds


def _datetime(value: int) -> datetime:
    return EPOCH + timedelta(microseconds=value)


def _record(row: tuple) -> MessageRecord:
    return MessageRecord(
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


class SQLiteMessageStore:
    def __init__(self, path: Path) -> None:
        SQLiteWatchStore(path)
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=1)
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
            raise _store_error("Message write failed", exc) from exc

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
            raise _store_error("Watched message write failed", exc) from exc

    def update_content(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        content: str,
        *,
        edited_at: datetime,
        cached_at: datetime,
    ) -> bool:
        """Apply a raw edit only to a message already known to be human and watched."""
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE messages SET content=?, edited_at_us=?, cached_at_us=? "
                    "WHERE guild_id=? AND channel_id=? AND message_id=?",
                    (
                        content,
                        _microseconds(edited_at),
                        _microseconds(cached_at),
                        guild_id,
                        channel_id,
                        message_id,
                    ),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise _store_error("Message edit failed", exc) from exc

    def delete_many(self, guild_id: int, channel_id: int, message_ids: set[int]) -> int:
        """Delete scoped IDs in bounded batches without needing message bodies."""
        if not message_ids:
            return 0
        if min(message_ids) < 1:
            raise ValueError("message identifiers must be positive")
        deleted = 0
        ordered = sorted(message_ids)
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                for offset in range(0, len(ordered), 500):
                    batch = ordered[offset : offset + 500]
                    placeholders = ",".join("?" for _ in batch)
                    cursor = connection.execute(
                        "DELETE FROM messages WHERE guild_id=? AND channel_id=? "
                        f"AND message_id IN ({placeholders})",
                        (guild_id, channel_id, *batch),
                    )
                    deleted += cursor.rowcount
        except sqlite3.Error as exc:
            raise _store_error("Message deletion failed", exc) from exc
        return deleted

    def prune_before(self, cutoff: datetime) -> int:
        """Retain records created at the exact cutoff and trim coverage to it."""
        cutoff_us = _microseconds(cutoff)
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                deleted = connection.execute(
                    "DELETE FROM messages WHERE created_at_us<?", (cutoff_us,)
                ).rowcount
                connection.execute("DELETE FROM coverage WHERE end_us<=?", (cutoff_us,))
                connection.execute(
                    "UPDATE OR REPLACE coverage SET start_us=? WHERE start_us<?",
                    (cutoff_us, cutoff_us),
                )
                connection.execute(
                    "DELETE FROM coverage_recheck WHERE end_us<=?", (cutoff_us,)
                )
                connection.execute(
                    "UPDATE OR REPLACE coverage_recheck SET start_us=? WHERE start_us<?",
                    (cutoff_us, cutoff_us),
                )
                return deleted
        except sqlite3.Error as exc:
            raise _store_error("Cache cleanup failed", exc) from exc

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
            raise _store_error("Message read failed", exc) from exc
        return [_record(row) for row in rows]

    def latest(
        self,
        guild_id: int,
        channel_id: int,
        start: datetime,
        end: datetime,
        limit: int,
        *,
        exclude_id: int | None = None,
    ) -> Sequence[MessageRecord]:
        """Return at most limit cached messages, newest first, for a count request."""
        if limit < 1:
            raise ValueError("limit must be positive")
        start_us, end_us = _microseconds(start), _microseconds(end)
        if start_us > end_us:
            raise ValueError("start must not follow end")
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT message_id, guild_id, channel_id, author_id, author_name, content, "
                    "created_at_us, edited_at_us, cached_at_us FROM messages "
                    "WHERE guild_id=? AND channel_id=? AND created_at_us>=? AND created_at_us<? "
                    "AND (? IS NULL OR message_id!=?) "
                    "ORDER BY created_at_us DESC, message_id DESC LIMIT ?",
                    (guild_id, channel_id, start_us, end_us, exclude_id, exclude_id, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _store_error("Latest message read failed", exc) from exc
        return [_record(row) for row in rows]

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
            raise _store_error("Coverage write failed", exc) from exc

    def coverage(self, guild_id: int, channel_id: int) -> Sequence[CoverageInterval]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT start_us, end_us FROM coverage "
                    "WHERE guild_id=? AND channel_id=? ORDER BY start_us, end_us",
                    (guild_id, channel_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _store_error("Coverage read failed", exc) from exc
        return [CoverageInterval(channel_id, _datetime(start), _datetime(end)) for start, end in rows]

    def recheck(self, guild_id: int, channel_id: int) -> Sequence[CoverageInterval]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT start_us, end_us FROM coverage_recheck "
                    "WHERE guild_id=? AND channel_id=? ORDER BY start_us, end_us",
                    (guild_id, channel_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise _store_error("Recheck read failed", exc) from exc
        return [CoverageInterval(channel_id, _datetime(start), _datetime(end)) for start, end in rows]

    def missing(self, guild_id: int, request: CoverageInterval) -> list[CoverageInterval]:
        return missing_intervals(
            request,
            self.coverage(guild_id, request.channel_id),
            recheck=self.recheck(guild_id, request.channel_id),
        )

    def mark_all_watched_recheck(
        self, start: datetime, end: datetime, *, reason: str
    ) -> int:
        """Require History revalidation after startup or a Gateway gap."""
        start_us, end_us = _microseconds(start), _microseconds(end)
        if start_us >= end_us:
            raise ValueError("recheck range must be nonempty")
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                channels = connection.execute(
                    "SELECT guild_id, channel_id FROM watched_channels"
                ).fetchall()
                connection.executemany(
                    "INSERT INTO coverage_recheck "
                    "(guild_id, channel_id, start_us, end_us, reason) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(guild_id, channel_id, start_us, end_us) "
                    "DO UPDATE SET reason=excluded.reason",
                    ((guild_id, channel_id, start_us, end_us, reason) for guild_id, channel_id in channels),
                )
                return len(channels)
        except sqlite3.Error as exc:
            raise _store_error("Recheck write failed", exc) from exc

    def commit_history_complete(
        self,
        guild_id: int,
        interval: CoverageInterval,
        records: Sequence[MessageRecord],
        *,
        exhausted: bool,
        expected_version: int,
        verified_at: datetime,
        fetched_after: datetime | None = None,
    ) -> bool:
        """Atomically publish a complete page pass and reconcile older cached rows."""
        if not exhausted:
            return False
        if any(
            record.guild_id != guild_id
            or record.channel_id != interval.channel_id
            or not interval.start <= record.created_at < interval.end
            for record in records
        ):
            raise ValueError("History messages must belong to the completed interval")
        start_us, end_us, verified_us = (
            _microseconds(interval.start),
            _microseconds(interval.end),
            _microseconds(verified_at),
        )
        fetched_after_us = _microseconds(fetched_after) if fetched_after is not None else None
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT version FROM guild_watch_meta WHERE guild_id=?", (guild_id,)
                ).fetchone()
                watched = connection.execute(
                    "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
                    (guild_id, interval.channel_id),
                ).fetchone()
                if row is None or row[0] != expected_version or watched is None:
                    return False
                if fetched_after_us is not None:
                    connection.execute("CREATE TEMP TABLE history_ids (message_id INTEGER PRIMARY KEY)")
                    connection.executemany(
                        "INSERT INTO history_ids(message_id) VALUES (?)",
                        ((record.message_id,) for record in records),
                    )
                    connection.execute(
                        "DELETE FROM messages WHERE guild_id=? AND channel_id=? "
                        "AND created_at_us>=? AND created_at_us<? AND cached_at_us<=? "
                        "AND NOT EXISTS (SELECT 1 FROM history_ids "
                        "WHERE history_ids.message_id=messages.message_id)",
                        (guild_id, interval.channel_id, start_us, end_us, fetched_after_us),
                    )
                for record in records:
                    if fetched_after_us is not None:
                        cached = connection.execute(
                            "SELECT cached_at_us FROM messages WHERE message_id=?",
                            (record.message_id,),
                        ).fetchone()
                        if cached is not None and cached[0] > fetched_after_us:
                            continue
                    self._upsert(connection, record, verified_at)
                connection.execute(
                    "INSERT INTO coverage "
                    "(guild_id, channel_id, start_us, end_us, verified_at_us) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(guild_id, channel_id, start_us, end_us) "
                    "DO UPDATE SET verified_at_us=excluded.verified_at_us",
                    (guild_id, interval.channel_id, start_us, end_us, verified_us),
                )
                stale = connection.execute(
                    "SELECT start_us, end_us, reason FROM coverage_recheck "
                    "WHERE guild_id=? AND channel_id=? AND end_us>? AND start_us<?",
                    (guild_id, interval.channel_id, start_us, end_us),
                ).fetchall()
                for stale_start, stale_end, reason in stale:
                    connection.execute(
                        "DELETE FROM coverage_recheck WHERE guild_id=? AND channel_id=? "
                        "AND start_us=? AND end_us=?",
                        (guild_id, interval.channel_id, stale_start, stale_end),
                    )
                    for remaining_start, remaining_end in (
                        (stale_start, min(stale_end, start_us)),
                        (max(stale_start, end_us), stale_end),
                    ):
                        if remaining_start < remaining_end:
                            connection.execute(
                                "INSERT OR IGNORE INTO coverage_recheck "
                                "(guild_id, channel_id, start_us, end_us, reason) "
                                "VALUES (?, ?, ?, ?, ?)",
                                (
                                    guild_id,
                                    interval.channel_id,
                                    remaining_start,
                                    remaining_end,
                                    reason,
                                ),
                            )
                return True
        except sqlite3.Error as exc:
            raise _store_error("History completion failed", exc) from exc
