"""1.4.3 식단: the diet channel and role of each server, and the day's steps already done."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.watch_store import SQLiteWatchStore

STAGES = ("call", "nag", "judge")
RUN_DAYS = 40


class SQLiteDietStore:
    """`diet_settings` (settings, in backups) and `diet_runs` (one row per server, day, step)."""

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

    def settings(self, guild_id: int) -> tuple[int | None, int | None]:
        """(channel, role); either may be None."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT channel_id, role_id FROM diet_settings WHERE guild_id=?", (guild_id,)
            ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def configured(self) -> list[tuple[int, int, int]]:
        """Servers with both a channel and a role: (server, channel, role)."""
        with self._connection() as connection:
            return [tuple(row) for row in connection.execute(
                "SELECT guild_id, channel_id, role_id FROM diet_settings "
                "WHERE channel_id IS NOT NULL AND role_id IS NOT NULL ORDER BY guild_id"
            )]

    def _set(self, guild_id: int, column: str, value: int | None) -> None:
        _positive(guild_id, *(() if value is None else (value,)))
        assert column in ("channel_id", "role_id")
        with self._connection() as connection, connection:
            connection.execute(
                f"INSERT INTO diet_settings (guild_id, {column}, updated_us) VALUES (?, ?, ?) "
                f"ON CONFLICT(guild_id) DO UPDATE SET {column}=excluded.{column}, "
                "updated_us=excluded.updated_us",
                (guild_id, value, _now_us()),
            )
            connection.execute(
                "DELETE FROM diet_settings WHERE guild_id=? AND channel_id IS NULL AND role_id IS NULL",
                (guild_id,),
            )

    def set_channel(self, guild_id: int, channel_id: int | None) -> None:
        self._set(guild_id, "channel_id", channel_id)

    def set_role(self, guild_id: int, role_id: int | None) -> None:
        self._set(guild_id, "role_id", role_id)

    def remove_channel(self, guild_id: int, channel_id: int) -> bool:
        with self._connection() as connection:
            changed = connection.execute(
                "SELECT 1 FROM diet_settings WHERE guild_id=? AND channel_id=?", (guild_id, channel_id)
            ).fetchone() is not None
        if changed:
            self.set_channel(guild_id, None)
        return changed

    def remove_role(self, guild_id: int, role_id: int) -> bool:
        with self._connection() as connection:
            changed = connection.execute(
                "SELECT 1 FROM diet_settings WHERE guild_id=? AND role_id=?", (guild_id, role_id)
            ).fetchone() is not None
        if changed:
            self.set_role(guild_id, None)
        return changed

    def claim(self, guild_id: int, day: str, stage: str, outcome: str, at: datetime) -> bool:
        """Record this step for the day; False when it was already recorded (do not run twice)."""
        assert stage in STAGES
        with self._connection() as connection, connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO diet_runs (guild_id, day, stage, outcome, done_us) "
                "VALUES (?, ?, ?, ?, ?)", (guild_id, day, stage, outcome, _us(at)),
            ).rowcount == 1
            connection.execute(
                "DELETE FROM diet_runs WHERE done_us < ?", (_us(at - timedelta(days=RUN_DAYS)),)
            )
        return inserted

    def finish(self, guild_id: int, day: str, stage: str, outcome: str) -> None:
        """The final outcome category of a claimed step."""
        with self._connection() as connection, connection:
            connection.execute(
                "UPDATE diet_runs SET outcome=? WHERE guild_id=? AND day=? AND stage=?",
                (outcome, guild_id, day, stage),
            )

    def done(self, guild_id: int, day: str) -> dict[str, str]:
        with self._connection() as connection:
            return dict(connection.execute(
                "SELECT stage, outcome FROM diet_runs WHERE guild_id=? AND day=?", (guild_id, day)
            ).fetchall())

    def keep_only(self, guild_ids: Iterable[int]) -> int:
        present = sorted(set(guild_ids))
        marks = ",".join("?" * len(present)) or "NULL"
        with self._connection() as connection, connection:
            removed = connection.execute(
                f"DELETE FROM diet_settings WHERE guild_id NOT IN ({marks})", present
            ).rowcount
            removed += connection.execute(
                f"DELETE FROM diet_runs WHERE guild_id NOT IN ({marks})", present
            ).rowcount
        return removed


def _positive(*ids: int) -> None:
    if any(value < 1 for value in ids):
        raise ValueError("Discord identifiers must be positive")


def _us(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _now_us() -> int:
    return _us(datetime.now(UTC))
