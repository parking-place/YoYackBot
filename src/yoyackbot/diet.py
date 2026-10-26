"""1.4.3 식단: the diet channel and role of each server, and the day's steps already done.

1.4.4: the exercise channel and role (the diet ones unless set), each person's daily estimates
for the weekly advice, and the weekly run of each server."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.watch_store import SQLiteWatchStore

STAGES = ("call", "nag", "judge")
RUN_DAYS = 40
SUMMARY_CHARS = 80


@dataclass(frozen=True)
class DailyRecord:
    """One person's estimated day (1.4.4): numbers may be None when the model could not tell."""

    user_id: int
    protein_g: int | None
    sugar_g: int | None
    foods: str
    exercise: str | None


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

    def _set(self, guild_id: int, column: str, value: int | None, table: str = "diet_settings") -> None:
        _positive(guild_id, *(() if value is None else (value,)))
        assert column in ("channel_id", "role_id") and table in ("diet_settings", "exercise_settings")
        with self._connection() as connection, connection:
            connection.execute(
                f"INSERT INTO {table} (guild_id, {column}, updated_us) VALUES (?, ?, ?) "
                f"ON CONFLICT(guild_id) DO UPDATE SET {column}=excluded.{column}, "
                "updated_us=excluded.updated_us",
                (guild_id, value, _now_us()),
            )
            connection.execute(
                f"DELETE FROM {table} WHERE guild_id=? AND channel_id IS NULL AND role_id IS NULL",
                (guild_id,),
            )

    def set_channel(self, guild_id: int, channel_id: int | None) -> None:
        self._set(guild_id, "channel_id", channel_id)

    def set_role(self, guild_id: int, role_id: int | None) -> None:
        self._set(guild_id, "role_id", role_id)

    def exercise_settings(self, guild_id: int) -> tuple[int | None, int | None]:
        """1.4.4: the exercise channel and role as set; either may be None (then the diet one)."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT channel_id, role_id FROM exercise_settings WHERE guild_id=?", (guild_id,)
            ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def exercise_target(self, guild_id: int) -> tuple[int | None, int | None]:
        """The channel and role exercise is read for: the exercise ones, else the diet ones."""
        channel, role = self.exercise_settings(guild_id)
        diet_channel, diet_role = self.settings(guild_id)
        return channel or diet_channel, role or diet_role

    def set_exercise_channel(self, guild_id: int, channel_id: int | None) -> None:
        self._set(guild_id, "channel_id", channel_id, "exercise_settings")

    def set_exercise_role(self, guild_id: int, role_id: int | None) -> None:
        self._set(guild_id, "role_id", role_id, "exercise_settings")

    def _remove(self, table: str, column: str, guild_id: int, value: int) -> bool:
        with self._connection() as connection:
            changed = connection.execute(
                f"SELECT 1 FROM {table} WHERE guild_id=? AND {column}=?", (guild_id, value)
            ).fetchone() is not None
        if changed:
            self._set(guild_id, column, None, table)
        return changed

    def remove_channel(self, guild_id: int, channel_id: int) -> bool:
        diet = self._remove("diet_settings", "channel_id", guild_id, channel_id)
        exercise = self._remove("exercise_settings", "channel_id", guild_id, channel_id)
        return diet or exercise

    def remove_role(self, guild_id: int, role_id: int) -> bool:
        diet = self._remove("diet_settings", "role_id", guild_id, role_id)
        exercise = self._remove("exercise_settings", "role_id", guild_id, role_id)
        return diet or exercise

    def save_daily(self, guild_id: int, day: str, records: Iterable[DailyRecord], at: datetime) -> int:
        """Replace that day's estimates for these people; older than 40 days go. Returns rows."""
        rows = [
            (guild_id, day, record.user_id, record.protein_g, record.sugar_g,
             record.foods[:SUMMARY_CHARS], (record.exercise or None) and record.exercise[:SUMMARY_CHARS],
             _us(at))
            for record in records
        ]
        cutoff = (at - timedelta(days=RUN_DAYS)).date().isoformat()
        with self._connection() as connection, connection:
            connection.executemany(
                "INSERT INTO diet_daily (guild_id, day, user_id, protein_g, sugar_g, foods, exercise, "
                "updated_us) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, day, user_id) DO "
                "UPDATE SET protein_g=excluded.protein_g, sugar_g=excluded.sugar_g, "
                "foods=excluded.foods, exercise=excluded.exercise, updated_us=excluded.updated_us",
                rows,
            )
            connection.execute("DELETE FROM diet_daily WHERE day < ?", (cutoff,))
        return len(rows)

    def week(self, guild_id: int, first_day: str, last_day: str) -> dict[int, list[tuple[str, DailyRecord]]]:
        """Each person's (day, record) from first_day to last_day (ISO dates, inclusive)."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT day, user_id, protein_g, sugar_g, foods, exercise FROM diet_daily "
                "WHERE guild_id=? AND day BETWEEN ? AND ? ORDER BY user_id, day",
                (guild_id, first_day, last_day),
            ).fetchall()
        found: dict[int, list[tuple[str, DailyRecord]]] = {}
        for day, user_id, protein, sugar, foods, exercise in rows:
            found.setdefault(user_id, []).append((day, DailyRecord(user_id, protein, sugar, foods, exercise)))
        return found

    def claim_week(self, guild_id: int, week: str, outcome: str, at: datetime) -> bool:
        """Record this week's advice once; False when it was already recorded."""
        with self._connection() as connection, connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO diet_week_runs (guild_id, week, outcome, done_us) VALUES (?, ?, ?, ?)",
                (guild_id, week, outcome, _us(at)),
            ).rowcount == 1
            connection.execute(
                "DELETE FROM diet_week_runs WHERE done_us < ?", (_us(at - timedelta(days=RUN_DAYS)),)
            )
        return inserted

    def finish_week(self, guild_id: int, week: str, outcome: str) -> None:
        with self._connection() as connection, connection:
            connection.execute(
                "UPDATE diet_week_runs SET outcome=? WHERE guild_id=? AND week=?", (outcome, guild_id, week)
            )

    def week_done(self, guild_id: int, week: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT outcome FROM diet_week_runs WHERE guild_id=? AND week=?", (guild_id, week)
            ).fetchone()
        return row[0] if row else None

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
            for table in ("diet_runs", "exercise_settings", "diet_daily", "diet_week_runs"):
                removed += connection.execute(
                    f"DELETE FROM {table} WHERE guild_id NOT IN ({marks})", present
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
