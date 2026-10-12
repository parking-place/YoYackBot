"""1.4.0 처형: the per-server log channel and the roles allowed to use `/처형` (optional tables)."""

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.watch_store import SQLiteWatchStore

EVENT_DAYS = 40  # long enough for this month's ranking


@dataclass(frozen=True)
class Ranking:
    """One period of /처형순위 (1.4.2)."""

    victims: list[tuple[int, int, int]]       # (member, times executed, dead seconds)
    executioners: list[tuple[int, int]]       # (member, executions)
    total: int


class SQLiteExecutionStore:
    """`execution_settings` holds one log channel per server (no row = no log); `execution_roles`
    the roles that may use `/처형`. Both are settings and included in backups."""

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

    def log_channel(self, guild_id: int) -> int | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT channel_id FROM execution_settings WHERE guild_id=?", (guild_id,)
            ).fetchone()
        return row[0] if row else None

    def set_log_channel(self, guild_id: int, channel_id: int | None) -> None:
        _positive(guild_id, *(() if channel_id is None else (channel_id,)))
        with self._connection() as connection, connection:
            if channel_id is None:
                connection.execute("DELETE FROM execution_settings WHERE guild_id=?", (guild_id,))
            else:
                connection.execute(
                    "INSERT INTO execution_settings (guild_id, channel_id, updated_us) VALUES (?, ?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, "
                    "updated_us=excluded.updated_us",
                    (guild_id, channel_id, _now_us()),
                )

    def roles(self, guild_id: int) -> frozenset[int]:
        with self._connection() as connection:
            return frozenset(row[0] for row in connection.execute(
                "SELECT role_id FROM execution_roles WHERE guild_id=?", (guild_id,)
            ))

    def set_roles(self, guild_id: int, role_ids: Iterable[int]) -> None:
        chosen = sorted(set(role_ids))
        _positive(guild_id, *chosen)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM execution_roles WHERE guild_id=?", (guild_id,))
            connection.executemany(
                "INSERT INTO execution_roles (guild_id, role_id, updated_us) VALUES (?, ?, ?)",
                [(guild_id, role_id, _now_us()) for role_id in chosen],
            )

    def remove_channel(self, guild_id: int, channel_id: int) -> bool:
        with self._connection() as connection, connection:
            return connection.execute(
                "DELETE FROM execution_settings WHERE guild_id=? AND channel_id=?", (guild_id, channel_id)
            ).rowcount > 0

    def remove_role(self, guild_id: int, role_id: int) -> bool:
        with self._connection() as connection, connection:
            return connection.execute(
                "DELETE FROM execution_roles WHERE guild_id=? AND role_id=?", (guild_id, role_id)
            ).rowcount > 0

    def record(
        self, guild_id: int, kind: str, target_id: int, executor_id: int | None, seconds: int,
        at: datetime,
    ) -> None:
        """One timeout change for /처형순위; records older than 40 days go at the same time."""
        _positive(guild_id, target_id, *(() if executor_id is None else (executor_id,)))
        with self._connection() as connection, connection:
            connection.execute(
                "INSERT INTO execution_events (guild_id, kind, target_id, executor_id, seconds, at_us) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, kind, target_id, executor_id, seconds, _us(at)),
            )
            connection.execute(
                "DELETE FROM execution_events WHERE at_us < ?",
                (_us(at - timedelta(days=EVENT_DAYS)),),
            )

    def ranking(self, guild_id: int, start: datetime, end: datetime, *, top: int = 5) -> Ranking:
        """Most executed (then longest dead) and most executing members in [start, end)."""
        span = (guild_id, _us(start), _us(end))
        with self._connection() as connection:
            victims = connection.execute(
                "SELECT target_id, SUM(kind='apply') AS times, MAX(SUM(seconds), 0) AS dead "
                "FROM execution_events WHERE guild_id=? AND at_us>=? AND at_us<? "
                "GROUP BY target_id HAVING times > 0 ORDER BY times DESC, dead DESC, target_id "
                "LIMIT ?", (*span, top),
            ).fetchall()
            executioners = connection.execute(
                "SELECT executor_id, COUNT(*) AS times FROM execution_events "
                "WHERE guild_id=? AND at_us>=? AND at_us<? AND kind='apply' "
                "AND executor_id IS NOT NULL GROUP BY executor_id "
                "ORDER BY times DESC, executor_id LIMIT ?", (*span, top),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM execution_events WHERE guild_id=? AND at_us>=? AND at_us<? "
                "AND kind='apply'", span,
            ).fetchone()[0]
        return Ranking([tuple(row) for row in victims], [tuple(row) for row in executioners], total)

    def remove_guild(self, guild_id: int) -> None:
        with self._connection() as connection, connection:
            connection.execute("DELETE FROM execution_settings WHERE guild_id=?", (guild_id,))
            connection.execute("DELETE FROM execution_roles WHERE guild_id=?", (guild_id,))
            connection.execute("DELETE FROM execution_events WHERE guild_id=?", (guild_id,))

    def keep_only(self, guild_ids: Iterable[int]) -> int:
        """Drop the settings of servers the bot is no longer in (e.g. left while rolled back)."""
        present = sorted(set(guild_ids))
        marks = ",".join("?" * len(present)) or "NULL"
        with self._connection() as connection, connection:
            removed = connection.execute(
                f"DELETE FROM execution_settings WHERE guild_id NOT IN ({marks})", present
            ).rowcount
            removed += connection.execute(
                f"DELETE FROM execution_roles WHERE guild_id NOT IN ({marks})", present
            ).rowcount
            removed += connection.execute(
                f"DELETE FROM execution_events WHERE guild_id NOT IN ({marks})", present
            ).rowcount
        return removed


def _positive(*ids: int) -> None:
    if any(value < 1 for value in ids):
        raise ValueError("Discord identifiers must be positive")


def _now_us() -> int:
    delta = datetime.now(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _us(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
