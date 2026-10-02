"""Resumable first-watch History import, followed by live Gateway storage."""

from __future__ import annotations

import asyncio
import sqlite3
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import discord
from aiohttp import ClientError

from yoyackbot.backfill_state import reset_recheck
from yoyackbot.domain import MessageRecord
from yoyackbot.history import DiscordHistorySource, HistoryPageSource
from yoyackbot.message_store import SQLiteMessageStore, _microseconds
from yoyackbot.parser import RouteKind, route_trigger
from yoyackbot.watch_store import SQLiteWatchStore, _new_backfill


class BackfillError(RuntimeError):
    """Safe backfill failure; never includes Discord message data."""

    def __init__(self, message: str, *, retryable: bool = True, kind: str = "transient") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind


START_NOTICE = "👋📥 안녕하시오. 요약을 위해 데이터 수집중이오. ⏳"
READY_NOTICE = "✅🎉 이제부터 요약을 해줄 수 있을 것 같소. 📝"
NOT_READY_NOTICE = "⏳ 참을성을 기르시오 아직 준비가 되지 않았소. 🧘"


class BackfillPageScheduler:
    """Bound History page concurrency without occupying global slots per Guild."""

    def __init__(self, *, global_limit: int = 3, per_guild_limit: int = 2) -> None:
        if global_limit < 1 or per_guild_limit < 1:
            raise ValueError("Backfill concurrency must be positive")
        self.global_limit = asyncio.Semaphore(global_limit)
        self.per_guild_limit = per_guild_limit
        self.guild_limits: dict[int, asyncio.Semaphore] = {}

    async def run(self, guild_id: int, work: Callable[[], Awaitable[bool]]) -> bool:
        if guild_id < 1:
            raise ValueError("guild_id must be positive")
        guild_limit = self.guild_limits.setdefault(
            guild_id, asyncio.Semaphore(self.per_guild_limit)
        )
        async with guild_limit, self.global_limit:
            return await work()


class RetryHolds:
    """In-memory backoff for channels whose retry state could not be saved.

    A failed defer/block leaves the database row runnable. Without a hold the worker
    would retry that channel on every tick instead of waiting for the database.
    """

    def __init__(self, *, first_seconds: float = 5, max_seconds: float = 300) -> None:
        if not 0 < first_seconds <= max_seconds:
            raise ValueError("Backoff must be positive and bounded")
        self.first_seconds = first_seconds
        self.max_seconds = max_seconds
        self._holds: dict[tuple[int, int], tuple[datetime, int]] = {}

    def __len__(self) -> int:
        return len(self._holds)

    def fail(self, state: BackfillState, now: datetime) -> float:
        key = (state.guild_id, state.channel_id)
        failures = self._holds.get(key, (now, 0))[1] + 1
        delay = min(self.max_seconds, self.first_seconds * 2 ** min(failures - 1, 16))
        self._holds[key] = (now + timedelta(seconds=delay), failures)
        return delay

    def clear(self, state: BackfillState) -> None:
        self._holds.pop((state.guild_id, state.channel_id), None)

    def held(self, state: BackfillState, now: datetime) -> bool:
        hold = self._holds.get((state.guild_id, state.channel_id))
        return hold is not None and now < hold[0]

    def wait_seconds(self, now: datetime) -> float | None:
        """Seconds until the earliest active hold ends, or None without active holds."""
        waits = [(until - now).total_seconds() for until, _ in self._holds.values() if now < until]
        return min(waits) if waits else None


def round_robin_backfills(states: Sequence[BackfillState]) -> tuple[BackfillState, ...]:
    """Give each Guild an initial scheduling turn while preserving its channel order."""
    groups: dict[int, deque[BackfillState]] = defaultdict(deque)
    for state in states:
        groups[state.guild_id].append(state)
    ordered = []
    while groups:
        for guild_id in tuple(groups):
            ordered.append(groups[guild_id].popleft())
            if not groups[guild_id]:
                del groups[guild_id]
    return tuple(ordered)


def _us(value: datetime) -> int:
    return _microseconds(value)


def _at(value_us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value_us)


@dataclass(frozen=True)
class BackfillState:
    guild_id: int
    channel_id: int
    token: str
    first_watch: bool
    started_us: int
    cutoff_us: int
    before_id: int
    phase: str
    finished_us: int | None
    overlap_start_us: int | None
    overlap_before_id: int | None
    verified_us: int | None
    retry_at_us: int
    started_notice_id: int | None
    ready_notice_id: int | None
    started_notice_attempt_us: int | None
    ready_notice_attempt_us: int | None
    blocked_reason: str | None

    @property
    def ready(self) -> bool:
        return self.phase == "ready"

    @property
    def cursor(self) -> int:
        if self.phase == "overlap":
            assert self.overlap_before_id is not None
            return self.overlap_before_id
        return self.before_id


def summary_ready(state: BackfillState | None) -> bool:
    """Ready only after the full collection or gap recheck and any first-watch ready notice."""
    return state is not None and state.ready and state.blocked_reason is None and not (
        state.first_watch and state.ready_notice_id is None
    )


class SQLiteBackfillStore:
    """Share the watch database so page records and cursor commit atomically."""

    def __init__(
        self, path: Path, *, retention_days: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= retention_days <= 30:
            raise ValueError("Retention must be between 1 and 30 days")
        self.watches = SQLiteWatchStore(path)
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _state(row: tuple) -> BackfillState:
        return BackfillState(
            row[0], row[1], row[2], bool(row[3]), row[4], row[5], row[6],
            row[7], row[8], row[9], row[10], row[11], row[12],
            row[13], row[14], row[15], row[16], row[17],
        )

    @staticmethod
    def _select() -> str:
        return (
            "SELECT guild_id, channel_id, token, first_watch, started_us, cutoff_us, "
            "before_id, phase, finished_us, overlap_start_us, overlap_before_id, "
            "verified_us, retry_at_us, started_notice_id, ready_notice_id, "
            "started_notice_attempt_us, ready_notice_attempt_us, blocked_reason "
            "FROM backfill_state "
        )

    def ensure_existing(self) -> int:
        """Backfill preexisting watches once on upgrade without first-watch notices."""
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                missing = connection.execute(
                    "SELECT w.guild_id, w.channel_id FROM watched_channels w "
                    "LEFT JOIN backfill_state b ON b.guild_id=w.guild_id "
                    "AND b.channel_id=w.channel_id WHERE b.channel_id IS NULL"
                ).fetchall()
                connection.executemany(
                    "INSERT INTO backfill_state "
                    "(guild_id, channel_id, token, first_watch, started_us, cutoff_us, "
                    "before_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (_new_backfill(guild_id, channel_id, first_watch=False)
                     for guild_id, channel_id in missing),
                )
                return len(missing)
        except sqlite3.Error as exc:
            raise BackfillError("Unable to prepare existing watched channels") from exc

    def get(self, guild_id: int, channel_id: int) -> BackfillState | None:
        try:
            with self.watches._connection() as connection:
                row = connection.execute(
                    self._select() + "WHERE guild_id=? AND channel_id=?",
                    (guild_id, channel_id),
                ).fetchone()
                return self._state(row) if row is not None else None
        except sqlite3.Error as exc:
            raise BackfillError("Unable to read initial collection state") from exc

    def pending(self, now: datetime, *, limit: int = 20) -> tuple[BackfillState, ...]:
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                # Consume recheck rows left by an older writer or a previous startup too.
                stale = connection.execute(
                    "SELECT b.guild_id, b.channel_id FROM backfill_state b "
                    "WHERE b.phase='ready' AND EXISTS (SELECT 1 FROM coverage_recheck c "
                    "WHERE c.guild_id=b.guild_id AND c.channel_id=b.channel_id AND c.end_us>?)",
                    (_us(now - timedelta(days=self.retention_days)),),
                ).fetchall()
                for guild_id, channel_id in stale:
                    reset_recheck(
                        connection, guild_id, channel_id, now=now,
                        retention_days=self.retention_days, reason="pending",
                    )
                rows = connection.execute(
                    self._select() + "WHERE (phase IN ('history', 'overlap') "
                    "OR (phase='ready' AND first_watch=1 AND ready_notice_id IS NULL)) "
                    "AND blocked_reason IS NULL AND retry_at_us<=? "
                    "ORDER BY started_us, guild_id, channel_id LIMIT ?",
                    (_us(now), limit),
                ).fetchall()
                return tuple(self._state(row) for row in rows)
        except sqlite3.Error as exc:
            raise BackfillError("Unable to list initial collections") from exc

    def readiness_snapshot(
        self, guild_id: int, channel_id: int, *, cutoff: datetime,
    ) -> tuple[BackfillState | None, int, bool]:
        """Read state, generation and relevant recheck markers from one SQLite snapshot."""
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN")
                row = connection.execute(
                    self._select() + "WHERE guild_id=? AND channel_id=?", (guild_id, channel_id),
                ).fetchone()
                state = self._state(row) if row is not None else None
                pending = connection.execute(
                    "SELECT 1 FROM coverage_recheck WHERE guild_id=? AND channel_id=? "
                    "AND end_us>? LIMIT 1", (guild_id, channel_id, _us(cutoff)),
                ).fetchone() is not None
                return state, state.started_us if state is not None else 0, pending
        except sqlite3.Error as exc:
            raise BackfillError("Unable to read collection readiness") from exc

    def defer(self, state: BackfillState, *, until: datetime) -> None:
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE backfill_state SET retry_at_us=? WHERE guild_id=? AND channel_id=? "
                    "AND token=? AND phase=? AND started_us=?",
                    (_us(until), state.guild_id, state.channel_id, state.token, state.phase,
                     state.started_us),
                )
        except sqlite3.Error as exc:
            raise BackfillError("Unable to defer initial collection") from exc

    def block(self, state: BackfillState, *, reason: str) -> bool:
        """Keep partial records and cursor, but stop repeating permanent failures."""
        if reason not in {"permission", "channel_gone", "invalid_page"}:
            raise ValueError("Invalid collection block reason")
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE backfill_state SET blocked_reason=?, retry_at_us=0 "
                    "WHERE guild_id=? AND channel_id=? AND token=? AND phase=? "
                    "AND started_us=? AND blocked_reason IS NULL",
                    (reason, state.guild_id, state.channel_id, state.token, state.phase,
                     state.started_us),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise BackfillError("Unable to block initial collection") from exc

    def resume_blocked(self, guild_id: int, channel_id: int) -> bool:
        """Called only after the Gateway reports accessible channel permissions."""
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "UPDATE backfill_state SET blocked_reason=NULL, retry_at_us=0 "
                    "WHERE guild_id=? AND channel_id=? AND phase IN ('history', 'overlap') "
                    "AND blocked_reason IN ('permission', 'channel_gone') "
                    "AND EXISTS (SELECT 1 FROM watched_channels w "
                    "WHERE w.guild_id=? AND w.channel_id=?)",
                    (guild_id, channel_id, guild_id, channel_id),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise BackfillError("Unable to resume initial collection") from exc

    def mark_notice_attempt(
        self, state: BackfillState, *, ready: bool, at: datetime
    ) -> bool:
        column = "ready_notice_attempt_us" if ready else "started_notice_attempt_us"
        id_column = "ready_notice_id" if ready else "started_notice_id"
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    f"UPDATE backfill_state SET {column}=? "
                    f"WHERE guild_id=? AND channel_id=? AND token=? AND phase=? "
                    f"AND started_us=? AND first_watch=1 AND {id_column} IS NULL",
                    (_us(at), state.guild_id, state.channel_id, state.token, state.phase,
                     state.started_us),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise BackfillError("Unable to prepare collection notice") from exc

    def record_notice(
        self, state: BackfillState, *, ready: bool, message_id: int
    ) -> bool:
        if message_id < 1:
            raise ValueError("Discord message ID must be positive")
        column = "ready_notice_id" if ready else "started_notice_id"
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    f"UPDATE backfill_state SET {column}=?, retry_at_us=0 "
                    f"WHERE guild_id=? AND channel_id=? AND token=? AND first_watch=1 "
                    f"AND started_us=? AND {column} IS NULL",
                    (message_id, state.guild_id, state.channel_id, state.token, state.started_us),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise BackfillError("Unable to record collection notice") from exc

    def schedule_ready_recheck(self, *, end: datetime, start: datetime | None = None) -> int:
        """Recheck retained edits/deletions and new messages from every work phase.

        ``start`` remains accepted for callers reporting their disconnection boundary; edits
        to older retained messages require a full pass regardless of that creation-time gap.
        """
        count = 0
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT guild_id, channel_id FROM watched_channels"
                ).fetchall()
                for guild_id, channel_id in rows:
                    count += reset_recheck(
                        connection, guild_id, channel_id, now=end,
                        retention_days=self.retention_days,
                        reason="gateway_gap" if start is not None else "startup",
                    )
            return count
        except sqlite3.Error as exc:
            raise BackfillError("Unable to schedule connection-gap check") from exc

    def history_boundary(self, state: BackfillState, *, at: datetime) -> int:
        try:
            with self.watches._connection() as connection:
                return SQLiteMessageStore._history_boundary(
                    connection, state.guild_id, state.channel_id, at,
                )
        except sqlite3.Error as exc:
            raise BackfillError("Unable to capture History observation boundary") from exc

    def save_page(
        self, state: BackfillState, records: Sequence[MessageRecord], *,
        next_cursor: int, next_phase: str, finished_at: datetime | None,
        cached_at: datetime,
        fetched_after_us: int | None = None, reconcile_lower_id: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> bool:
        """Reject stale watch generations before any message from that page is written."""
        try:
            with self.watches._connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT phase, before_id, overlap_before_id, blocked_reason, "
                    "started_us, cutoff_us, finished_us, overlap_start_us "
                    "FROM backfill_state "
                    "WHERE guild_id=? AND channel_id=? AND token=?",
                    (state.guild_id, state.channel_id, state.token),
                ).fetchone()
                watched = connection.execute(
                    "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
                    (state.guild_id, state.channel_id),
                ).fetchone()
                if row is None or watched is None or row[3] is not None or row[0] != state.phase or (
                    row[2] if state.phase == "overlap" else row[1]
                ) != state.cursor or row[4:] != (
                    state.started_us, state.cutoff_us, state.finished_us, state.overlap_start_us,
                ):
                    return False
                current_cutoff_us = _us((clock or self.clock)() - timedelta(days=self.retention_days))
                for record in records:
                    if record.guild_id != state.guild_id or record.channel_id != state.channel_id:
                        raise BackfillError("History page channel mismatch")
                retained = tuple(
                    record for record in records if _us(record.created_at) >= current_cutoff_us
                )
                if fetched_after_us is not None and reconcile_lower_id is not None:
                    lower_us = state.cutoff_us if state.phase == "history" else state.overlap_start_us
                    upper_us = (
                        state.finished_us if state.finished_us is not None else state.started_us
                    )
                    assert lower_us is not None
                    if max(lower_us, current_cutoff_us) < upper_us and reconcile_lower_id < state.cursor:
                        SQLiteMessageStore._reconcile_page(
                            connection, state.guild_id, state.channel_id, retained,
                            lower_id=reconcile_lower_id, before_id=state.cursor,
                            start_us=lower_us, end_us=upper_us, fetched_after_us=fetched_after_us,
                            cached_at=cached_at, cutoff_us=current_cutoff_us,
                        )
                else:
                    # Compatibility for direct import adapters; the worker always reconciles.
                    for record in retained:
                        SQLiteMessageStore._upsert(connection, record, cached_at)
                if state.phase == "history":
                    if next_phase == "overlap":
                        assert finished_at is not None
                        history_end_us = state.finished_us or state.started_us
                        finished_us = max(_us(finished_at), history_end_us)
                        overlap_before = discord.utils.time_snowflake(
                            _at(finished_us), high=True
                        ) + 1
                        connection.execute(
                            "UPDATE backfill_state SET before_id=?, phase='overlap', "
                            "finished_us=?, overlap_start_us=?, "
                            "overlap_before_id=?, retry_at_us=0 "
                            "WHERE guild_id=? AND channel_id=? AND token=?",
                            (next_cursor, finished_us, history_end_us, overlap_before,
                             state.guild_id, state.channel_id, state.token),
                        )
                    else:
                        connection.execute(
                            "UPDATE backfill_state SET before_id=?, retry_at_us=0 "
                            "WHERE guild_id=? AND channel_id=? AND token=?",
                            (next_cursor, state.guild_id, state.channel_id, state.token),
                        )
                elif next_phase == "ready":
                    # Every retained page and the live overlap passed for this exact generation.
                    connection.execute(
                        "DELETE FROM coverage_recheck WHERE guild_id=? AND channel_id=?",
                        (state.guild_id, state.channel_id),
                    )
                    connection.execute(
                        "UPDATE backfill_state SET phase='ready', overlap_before_id=?, "
                        "verified_us=finished_us, retry_at_us=0 "
                        "WHERE guild_id=? AND channel_id=? AND token=?",
                        (next_cursor, state.guild_id, state.channel_id, state.token),
                    )
                else:
                    connection.execute(
                        "UPDATE backfill_state SET overlap_before_id=?, retry_at_us=0 "
                        "WHERE guild_id=? AND channel_id=? AND token=?",
                        (next_cursor, state.guild_id, state.channel_id, state.token),
                    )
                return True
        except sqlite3.Error as exc:
            raise BackfillError("Unable to store initial collection page") from exc


def _record(message: discord.Message, guild_id: int, channel_id: int) -> MessageRecord | None:
    if (
        message.webhook_id is not None or message.author.bot
        or message.type not in {discord.MessageType.default, discord.MessageType.reply}
        or route_trigger(message.content).kind is not RouteKind.NONE
    ):
        return None
    return MessageRecord(
        message.id, guild_id, channel_id, message.author.id,
        getattr(message.author, "display_name", None)
        or getattr(message.author, "name", "unknown"),
        message.content, message.created_at, message.edited_at,
        has_attachment=bool(getattr(message, "attachments", ())),
        is_reply=message.type is discord.MessageType.reply,
    )


class InitialBackfill:
    def __init__(
        self, store: SQLiteBackfillStore,
        source: HistoryPageSource | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        page_size: int = 100,
        retention_days: int | None = None,
    ) -> None:
        if not 1 <= page_size <= 100:
            raise ValueError("Discord History page size must be 1..100")
        self.store = store
        self.source = source or DiscordHistorySource()
        self.clock = clock or store.clock
        self.page_size = page_size
        self.retention_days = store.retention_days if retention_days is None else retention_days
        if not 1 <= self.retention_days <= 30 or self.retention_days != store.retention_days:
            raise ValueError("Worker retention must match its store's 1..30 day policy")

    async def step(
        self, channel: discord.TextChannel, state: BackfillState,
        *, can_continue: Callable[[], bool] | None = None,
    ) -> bool:
        """Import one bounded page so other watched channels can make progress."""
        if state.phase not in {"history", "overlap"}:
            return False
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != state.channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != state.guild_id
        ):
            raise BackfillError("History channel mismatch")
        fetched_after_us = await asyncio.to_thread(
            self.store.history_boundary, state, at=self.clock(),
        )
        lower_us = max(
            state.cutoff_us if state.phase == "history"
            else state.overlap_start_us if state.overlap_start_us is not None else state.started_us,
            _us(self.clock() - timedelta(days=self.retention_days)),
        )
        upper_us = state.finished_us if state.finished_us is not None else state.started_us
        lower_id = discord.utils.time_snowflake(_at(lower_us))
        try:
            page = (
                await self.source.fetch_page(
                    channel, before=state.cursor, limit=self.page_size, after=lower_id - 1,
                ) if lower_us < upper_us else []
            )
        except discord.HTTPException as exc:
            if exc.status in {401, 403, 404}:
                kind = "channel_gone" if exc.status == 404 else "permission"
                raise BackfillError(
                    "History access denied", retryable=False, kind=kind
                ) from exc
            raise BackfillError("History page unavailable") from exc
        except (ClientError, OSError) as exc:
            raise BackfillError("History page unavailable") from exc
        if can_continue is not None and not can_continue():
            raise BackfillError("History access changed", retryable=False, kind="permission")
        if len(page) > self.page_size or any(
            message.id >= state.cursor
            or getattr(message.channel, "id", None) != state.channel_id
            or getattr(getattr(message, "guild", None), "id", None) != state.guild_id
            for message in page
        ) or any(left.id <= right.id for left, right in pairwise(page)):
            raise BackfillError(
                "Invalid History page", retryable=False, kind="invalid_page"
            )
        # Retention can move while Discord is responding; never hand expired rows to the writer.
        lower_us = max(lower_us, _us(self.clock() - timedelta(days=self.retention_days)))
        records = tuple(
            record for message in page
            if lower_us <= _us(message.created_at) < upper_us
            if (record := _record(message, state.guild_id, state.channel_id)) is not None
        )
        oldest_us = _us(page[-1].created_at) if page else 0
        exhausted = len(page) < self.page_size or oldest_us < lower_us
        next_phase = (
            ("overlap" if state.phase == "history" else "ready")
            if exhausted else state.phase
        )
        next_cursor = page[-1].id if page else state.cursor
        return await asyncio.to_thread(
            self.store.save_page, state, records,
            next_cursor=next_cursor, next_phase=next_phase,
            finished_at=self.clock() if next_phase == "overlap" else None,
            cached_at=self.clock(),
            fetched_after_us=fetched_after_us,
            reconcile_lower_id=lower_id if exhausted else page[-1].id,
            clock=self.clock,
        )


class BackfillNotifier:
    """Persist and reconcile channel announcements around uncertain Discord sends."""

    def __init__(
        self, store: SQLiteBackfillStore, *, bot_user_id: Callable[[], int | None],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.bot_user_id = bot_user_id
        self.clock = clock or (lambda: datetime.now(UTC))

    async def ensure(
        self, channel: discord.TextChannel, state: BackfillState, *, ready: bool
    ) -> bool:
        if not state.first_watch:
            return True
        current, generation, pending = await asyncio.to_thread(
            self.store.readiness_snapshot, state.guild_id, state.channel_id,
            cutoff=self.clock() - timedelta(days=self.store.retention_days),
        )
        if (current is None or current.token != state.token or generation != state.started_us
                or current.blocked_reason is not None):
            return False
        if (ready and (not current.ready or pending)) or (not ready and current.ready):
            return False
        notice_id = current.ready_notice_id if ready else current.started_notice_id
        if notice_id is not None:
            return True
        author_id = self.bot_user_id()
        if author_id is None:
            raise BackfillError("Bot account is not ready to announce collection")
        content = READY_NOTICE if ready else START_NOTICE
        attempt_us = (
            current.ready_notice_attempt_us if ready else current.started_notice_attempt_us
        )
        if attempt_us is not None:
            after = discord.Object(id=discord.utils.time_snowflake(_at(attempt_us)) - 1)
            try:
                async for message in channel.history(
                    limit=100, after=after, oldest_first=True
                ):
                    if message.author.id == author_id and message.content == content:
                        return await asyncio.to_thread(
                            self.store.record_notice, current,
                            ready=ready, message_id=message.id,
                        )
            except (discord.HTTPException, ClientError, OSError) as exc:
                raise BackfillError("Unable to reconcile collection notice") from exc
        if not await asyncio.to_thread(
            self.store.mark_notice_attempt, current, ready=ready, at=self.clock()
        ):
            return False
        try:
            posted = await channel.send(
                content, allowed_mentions=discord.AllowedMentions.none()
            )
        except (discord.HTTPException, ClientError, OSError) as exc:
            raise BackfillError("Unable to post collection notice") from exc
        return await asyncio.to_thread(
            self.store.record_notice, current, ready=ready, message_id=posted.id
        )
