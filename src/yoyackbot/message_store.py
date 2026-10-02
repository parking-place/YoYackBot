"""Guild-scoped SQLite message and coverage storage."""

import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path

from yoyackbot.backfill_state import reset_recheck
from yoyackbot.coverage import missing_intervals
from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.input_files import MIN_MESSAGE_LINE_BYTES, ConversationTooLarge
from yoyackbot.watch_store import SQLiteWatchStore

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# Rows materialized per SQLite fetch while a selection is checked against the input budget.
READ_BATCH_ROWS = 128
_SELECT_WITH_REPLY = (
    "SELECT m.message_id, m.guild_id, m.channel_id, m.author_id, m.author_name, m.content, "
    "m.created_at_us, m.edited_at_us, m.cached_at_us, m.has_attachment, m.is_reply, r.target_id "
    "FROM messages m LEFT JOIN message_reply_refs r ON r.guild_id=m.guild_id "
    "AND r.channel_id=m.channel_id AND r.message_id=m.message_id "
)


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
        has_attachment=bool(row[9]),
        is_reply=bool(row[10]),
        reply_to_message_id=(
            row[11] if len(row) > 11 and row[10] and row[11] is not None
            and 0 < row[11] < row[0] else None
        ),
    )


class SQLiteMessageStore:
    def __init__(
        self, path: Path, *, retention_days: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= retention_days <= 30:
            raise ValueError("Cache retention must be between 1 and 30 days")
        SQLiteWatchStore(path)
        self.path = path
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(UTC))

    def _cutoff_us(self) -> int:
        return _microseconds(self.clock() - timedelta(days=self.retention_days))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA secure_delete=ON")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _history_boundary(
        connection: sqlite3.Connection, guild_id: int, channel_id: int, at: datetime,
    ) -> int:
        """Order a fetch before subsequent writes even when the wall clock is unchanged."""
        row = connection.execute(
            "SELECT MAX(cached_at_us) FROM messages WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
        observed = row[0] if row is not None else None
        watermark = connection.execute(
            "SELECT last_us FROM cache_observation_clock WHERE singleton=1"
        ).fetchone()
        return max(
            _microseconds(at), observed + 1 if observed is not None else _microseconds(at),
            watermark[0] + 1 if watermark is not None else _microseconds(at),
        )

    @staticmethod
    def _record_observation(connection: sqlite3.Connection, observed_us: int) -> None:
        connection.execute(
            "INSERT INTO cache_observation_clock(singleton, last_us) VALUES (1, ?) "
            "ON CONFLICT(singleton) DO UPDATE SET last_us=MAX(last_us, excluded.last_us)",
            (observed_us,),
        )

    def history_boundary(
        self, guild_id: int, channel_id: int, *, at: datetime | None = None,
    ) -> int:
        try:
            with self._connection() as connection:
                return self._history_boundary(connection, guild_id, channel_id, at or self.clock())
        except sqlite3.Error as exc:
            raise _store_error("History observation read failed", exc) from exc

    @staticmethod
    def _upsert(
        connection: sqlite3.Connection, record: MessageRecord, cached_at: datetime,
        *, cutoff_us: int | None = None,
    ) -> bool:
        if min(record.message_id, record.guild_id, record.channel_id, record.author_id) < 1:
            raise ValueError("message identifiers must be positive")
        if cutoff_us is not None and _microseconds(record.created_at) < cutoff_us:
            return False
        if record.edited_at is not None and record.edited_at < record.created_at:
            return False
        deleted = connection.execute(
            "SELECT 1 FROM deleted_messages WHERE guild_id=? AND channel_id=? AND message_id=?",
            (record.guild_id, record.channel_id, record.message_id),
        ).fetchone()
        if deleted is not None:
            return False
        values = (
            record.message_id,
            record.guild_id,
            record.channel_id,
            record.author_id,
            record.author_name,
            record.content,
            _microseconds(record.created_at),
            _microseconds(record.edited_at) if record.edited_at is not None else None,
            SQLiteMessageStore._history_boundary(
                connection, record.guild_id, record.channel_id, cached_at,
            ),
            int(record.has_attachment),
            int(record.is_reply),
        )
        cursor = connection.execute(
            "INSERT INTO messages (message_id, guild_id, channel_id, author_id, "
            "author_name, content, created_at_us, edited_at_us, cached_at_us, "
            "has_attachment, is_reply) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(message_id) DO UPDATE SET author_id=excluded.author_id, "
            "author_name=excluded.author_name, content=excluded.content, "
            "edited_at_us=excluded.edited_at_us, "
            "cached_at_us=MAX(messages.cached_at_us, excluded.cached_at_us), "
            "has_attachment=excluded.has_attachment, is_reply=excluded.is_reply "
            "WHERE messages.guild_id=excluded.guild_id "
            "AND messages.channel_id=excluded.channel_id "
            "AND ((messages.edited_at_us IS NULL AND excluded.edited_at_us IS NOT NULL) "
            "OR (excluded.edited_at_us>messages.edited_at_us) "
            "OR (excluded.edited_at_us IS messages.edited_at_us "
            "AND excluded.content=messages.content))",
            values,
        )
        if record.reply_to_message_id is not None:
            # Reply targets never change; link only a stored, undeleted message to a live target.
            connection.execute(
                "INSERT OR IGNORE INTO message_reply_refs (guild_id, channel_id, message_id, "
                "target_id, observed_us) SELECT ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM messages "
                "WHERE message_id=? AND guild_id=? AND channel_id=?) AND NOT EXISTS (SELECT 1 FROM "
                "deleted_messages WHERE guild_id=? AND channel_id=? AND message_id=?)",
                (record.guild_id, record.channel_id, record.message_id,
                 record.reply_to_message_id, _microseconds(cached_at),
                 record.message_id, record.guild_id, record.channel_id,
                 record.guild_id, record.channel_id, record.reply_to_message_id),
            )
        if cursor.rowcount != 1:
            existing = connection.execute(
                "SELECT guild_id, channel_id FROM messages WHERE message_id=?",
                (record.message_id,),
            ).fetchone()
            if existing != (record.guild_id, record.channel_id):
                raise MessageStoreError("Message ID belongs to another channel")
            return False
        SQLiteMessageStore._record_observation(connection, values[8])
        return True

    @staticmethod
    def _reconcile_page(
        connection: sqlite3.Connection, guild_id: int, channel_id: int,
        records: Sequence[MessageRecord], *, lower_id: int, before_id: int,
        start_us: int, end_us: int, fetched_after_us: int, cached_at: datetime,
        cutoff_us: int,
    ) -> int:
        """Reconcile one complete validated page inside the caller's write transaction.

        Snowflake bounds avoid treating a partly fetched millisecond as complete.
        The caller owns generation checks, cursor updates, and coverage completion.
        """
        if (
            not connection.in_transaction or min(guild_id, channel_id) < 1
            or lower_id < 0 or before_id < lower_id or start_us >= end_us
            or len(records) > 100
        ):
            raise ValueError("Invalid History reconciliation page")
        if len({record.message_id for record in records}) != len(records) or any(
            record.guild_id != guild_id or record.channel_id != channel_id
            or not lower_id <= record.message_id < before_id
            or not start_us <= _microseconds(record.created_at) < end_us
            for record in records
        ):
            raise ValueError("History messages must belong to the completed page")
        lower_us = max(start_us, cutoff_us)
        if lower_us >= end_us:
            return 0
        retained = tuple(record for record in records if _microseconds(record.created_at) >= lower_us)
        ids = tuple(record.message_id for record in retained)
        absent = f"AND message_id NOT IN ({','.join('?' for _ in ids)})" if ids else ""
        deleted = connection.execute(
            "DELETE FROM messages WHERE guild_id=? AND channel_id=? "
            "AND message_id>=? AND message_id<? AND created_at_us>=? AND created_at_us<? "
            "AND cached_at_us<? " + absent,
            (guild_id, channel_id, lower_id, before_id, lower_us, end_us, fetched_after_us, *ids),
        ).rowcount
        for record in retained:
            current = connection.execute(
                "SELECT cached_at_us FROM messages WHERE message_id=? "
                "AND guild_id=? AND channel_id=?",
                (record.message_id, guild_id, channel_id),
            ).fetchone()
            if current is not None and current[0] >= fetched_after_us:
                continue
            SQLiteMessageStore._upsert(connection, record, cached_at, cutoff_us=cutoff_us)
        return deleted

    def upsert(self, record: MessageRecord, *, cached_at: datetime) -> None:
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                self._upsert(
                    connection, record, max(cached_at, self.clock()),
                    cutoff_us=self._cutoff_us(),
                )
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
                cutoff_us = self._cutoff_us()
                if _microseconds(record.created_at) < cutoff_us:
                    return False
                if record.edited_at is None:
                    current = connection.execute(
                        "SELECT content FROM messages "
                        "WHERE guild_id=? AND channel_id=? AND message_id=?",
                        (record.guild_id, record.channel_id, record.message_id),
                    ).fetchone()
                    if current is not None and current[0] != record.content:
                        self._unknown_edit(
                            connection, record.guild_id, record.channel_id, record.message_id,
                            cached_at=cached_at,
                        )
                        return False
                return self._upsert(
                    connection, record, max(cached_at, self.clock()), cutoff_us=cutoff_us,
                )
        except sqlite3.Error as exc:
            raise _store_error("Watched message write failed", exc) from exc

    def update_content(
        self,
        guild_id: int,
        channel_id: int,
        message_id: int,
        content: str,
        *,
        edited_at: datetime | None,
        cached_at: datetime,
    ) -> bool:
        """Apply a raw edit only to a message already known to be human and watched."""
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT created_at_us, edited_at_us FROM messages "
                    "WHERE guild_id=? AND channel_id=? AND message_id=? "
                    "AND EXISTS (SELECT 1 FROM watched_channels w "
                    "WHERE w.guild_id=messages.guild_id AND w.channel_id=messages.channel_id)",
                    (guild_id, channel_id, message_id),
                ).fetchone()
                if current is None or current[0] < self._cutoff_us():
                    return False
                if edited_at is None:
                    self._unknown_edit(
                        connection, guild_id, channel_id, message_id, cached_at=cached_at,
                    )
                    return False
                edited_us = _microseconds(edited_at)
                if edited_us < current[0] or (
                    current[1] is not None and edited_us <= current[1]
                ):
                    return False
                observed_us = self._history_boundary(
                    connection, guild_id, channel_id, max(cached_at, self.clock()),
                )
                cursor = connection.execute(
                    "UPDATE messages SET content=?, edited_at_us=?, "
                    "cached_at_us=MAX(cached_at_us, ?) "
                    "WHERE guild_id=? AND channel_id=? AND message_id=?",
                    (
                        content,
                        edited_us,
                        observed_us,
                        guild_id,
                        channel_id,
                        message_id,
                    ),
                )
                if cursor.rowcount == 1:
                    self._record_observation(connection, observed_us)
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise _store_error("Message edit failed", exc) from exc

    def _unknown_edit(
        self, connection: sqlite3.Connection, guild_id: int, channel_id: int, message_id: int,
        *, cached_at: datetime,
    ) -> None:
        """Keep ambiguous content and invalidate in-flight History in the same transaction."""
        if reset_recheck(
            connection, guild_id, channel_id, now=self.clock(),
            retention_days=self.retention_days, reason="unknown_edit_timestamp",
        ):
            observed_us = self._history_boundary(
                connection, guild_id, channel_id, max(cached_at, self.clock()),
            )
            connection.execute(
                "UPDATE messages SET cached_at_us=MAX(cached_at_us, ?) "
                "WHERE guild_id=? AND channel_id=? AND message_id=?",
                (
                    observed_us,
                    guild_id, channel_id, message_id,
                ),
            )
            self._record_observation(connection, observed_us)

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
                watched = connection.execute(
                    "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
                    (guild_id, channel_id),
                ).fetchone()
                if watched is not None:
                    deleted_at_us = _microseconds(self.clock())
                    connection.executemany(
                        "INSERT INTO deleted_messages "
                        "(guild_id, channel_id, message_id, deleted_at_us) "
                        "VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, channel_id, message_id) "
                        "DO UPDATE SET deleted_at_us=excluded.deleted_at_us",
                        ((guild_id, channel_id, message_id, deleted_at_us)
                         for message_id in ordered),
                    )
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
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cutoff_us = max(_microseconds(cutoff), self._cutoff_us())
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
                connection.execute(
                    "DELETE FROM deleted_messages WHERE deleted_at_us<?", (cutoff_us,)
                )
                return deleted
        except sqlite3.Error as exc:
            raise _store_error("Cache cleanup failed", exc) from exc

    def recent(
        self, guild_id: int, channel_id: int, start: datetime, end: datetime,
        *, exclude_id: int | None = None, max_bytes: int | None = None,
        on_rows: Callable[[int], None] | None = None,
    ) -> Sequence[MessageRecord]:
        """Oldest first; with max_bytes, stop reading as soon as the input cannot fit."""
        start_us, end_us = _microseconds(start), _microseconds(end)
        if start_us > end_us:
            raise ValueError("start must not follow end")
        start_us = max(start_us, self._cutoff_us())
        if start_us >= end_us:
            return []
        return self._read(
            _SELECT_WITH_REPLY
            + "WHERE m.guild_id=? AND m.channel_id=? AND m.created_at_us>=? "
            "AND m.created_at_us<? AND (? IS NULL OR m.message_id!=?) "
            "ORDER BY m.created_at_us, m.message_id",
            (guild_id, channel_id, start_us, end_us, exclude_id, exclude_id),
            failure="Message read failed", max_bytes=max_bytes, on_rows=on_rows,
        )

    def created_at(self, guild_id: int, channel_id: int, message_id: int) -> datetime | None:
        """A cached message's creation time in this channel (1.3.0 reply range)."""
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT created_at_us FROM messages WHERE guild_id=? AND channel_id=? "
                    "AND message_id=? AND created_at_us>=?",
                    (guild_id, channel_id, message_id, self._cutoff_us()),
                ).fetchone()
        except sqlite3.Error as exc:
            raise _store_error("Message lookup failed", exc) from exc
        return _datetime(row[0]) if row is not None else None

    def count_between(
        self, guild_id: int, channel_id: int, start: datetime, end: datetime,
        *, exclude_id: int | None = None,
    ) -> int:
        try:
            with self._connection() as connection:
                return connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE guild_id=? AND channel_id=? "
                    "AND created_at_us>=? AND created_at_us<? AND (? IS NULL OR message_id!=?)",
                    (guild_id, channel_id, max(_microseconds(start), self._cutoff_us()),
                     _microseconds(end), exclude_id, exclude_id),
                ).fetchone()[0]
        except sqlite3.Error as exc:
            raise _store_error("Message count failed", exc) from exc

    def latest(
        self,
        guild_id: int,
        channel_id: int,
        start: datetime,
        end: datetime,
        limit: int,
        *,
        exclude_id: int | None = None,
        max_bytes: int | None = None,
        on_rows: Callable[[int], None] | None = None,
    ) -> Sequence[MessageRecord]:
        """Return at most limit cached messages, newest first, for a count request."""
        if limit < 1:
            raise ValueError("limit must be positive")
        start_us, end_us = _microseconds(start), _microseconds(end)
        if start_us > end_us:
            raise ValueError("start must not follow end")
        start_us = max(start_us, self._cutoff_us())
        if start_us >= end_us:
            return []
        return self._read(
            _SELECT_WITH_REPLY
            + "WHERE m.guild_id=? AND m.channel_id=? AND m.created_at_us>=? "
            "AND m.created_at_us<? AND (? IS NULL OR m.message_id!=?) "
            "ORDER BY m.created_at_us DESC, m.message_id DESC LIMIT ?",
            (guild_id, channel_id, start_us, end_us, exclude_id, exclude_id, limit),
            failure="Latest message read failed", max_bytes=max_bytes, on_rows=on_rows,
        )

    def _read(
        self, query: str, parameters: tuple, *, failure: str, max_bytes: int | None,
        on_rows: Callable[[int], None] | None,
    ) -> list[MessageRecord]:
        """Fetch bounded batches; the byte check runs before the next batch is materialized.

        Each row costs at least its body and the smallest serialized message line, so a
        selection over max_bytes can never become a model input and is refused early.
        """
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        records: list[MessageRecord] = []
        content_bytes = 0
        try:
            with self._connection() as connection:
                cursor = connection.execute(query, parameters)
                try:
                    while batch := cursor.fetchmany(READ_BATCH_ROWS):
                        if on_rows is not None:
                            on_rows(len(batch))
                        for row in batch:
                            record = _record(row)
                            if max_bytes is not None:
                                content_bytes += len(record.content.encode("utf-8"))
                                if max(
                                    content_bytes, (len(records) + 1) * MIN_MESSAGE_LINE_BYTES,
                                ) > max_bytes:
                                    raise ConversationTooLarge(
                                        "Cached conversation exceeds configured input size"
                                    )
                            records.append(record)
                finally:
                    cursor.close()
        except sqlite3.Error as exc:
            raise _store_error(failure, exc) from exc
        return records

    def mark_covered(
        self, guild_id: int, interval: CoverageInterval, *, verified_at: datetime
    ) -> None:
        if guild_id < 1 or interval.channel_id < 1:
            raise ValueError("Guild and channel identifiers must be positive")
        try:
            with self._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                start_us = max(_microseconds(interval.start), self._cutoff_us())
                end_us = _microseconds(interval.end)
                if start_us >= end_us:
                    return
                connection.execute(
                    "INSERT INTO coverage "
                    "(guild_id, channel_id, start_us, end_us, verified_at_us) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(guild_id, channel_id, start_us, end_us) "
                    "DO UPDATE SET verified_at_us=excluded.verified_at_us",
                    (
                        guild_id,
                        interval.channel_id,
                        start_us,
                        end_us,
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
                start_us = max(start_us, self._cutoff_us())
                if start_us >= end_us:
                    return 0
                channels = connection.execute(
                    "SELECT guild_id, channel_id FROM watched_channels"
                ).fetchall()
                for guild_id, channel_id in channels:
                    reset_recheck(
                        connection, guild_id, channel_id, now=end,
                        retention_days=self.retention_days, reason=reason,
                    )
                    connection.execute(
                        "DELETE FROM coverage_recheck WHERE guild_id=? AND channel_id=?",
                        (guild_id, channel_id),
                    )
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
                cutoff_us = self._cutoff_us()
                start_us = max(start_us, cutoff_us)
                row = connection.execute(
                    "SELECT version FROM guild_watch_meta WHERE guild_id=?", (guild_id,)
                ).fetchone()
                watched = connection.execute(
                    "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
                    (guild_id, interval.channel_id),
                ).fetchone()
                if row is None or row[0] != expected_version or watched is None:
                    return False
                if start_us >= end_us:
                    return True
                records = tuple(
                    record for record in records if _microseconds(record.created_at) >= cutoff_us
                )
                if fetched_after_us is not None:
                    connection.execute("CREATE TEMP TABLE history_ids (message_id INTEGER PRIMARY KEY)")
                    connection.executemany(
                        "INSERT INTO history_ids(message_id) VALUES (?)",
                        ((record.message_id,) for record in records),
                    )
                    connection.execute(
                        "DELETE FROM messages WHERE guild_id=? AND channel_id=? "
                        "AND created_at_us>=? AND created_at_us<? AND cached_at_us<? "
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
                        if cached is not None and cached[0] >= fetched_after_us:
                            continue
                    self._upsert(
                        connection, record, max(verified_at, self.clock()), cutoff_us=cutoff_us,
                    )
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
