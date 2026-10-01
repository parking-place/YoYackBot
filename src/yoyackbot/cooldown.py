"""Persist only successful summary publication times and bounded expiry."""

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from yoyackbot.message_store import _datetime, _microseconds
from yoyackbot.watch_store import SQLiteWatchStore


class CooldownStoreError(RuntimeError):
    """The success cooldown could not be persisted or read."""


class SQLiteCooldownStore:
    def __init__(self, path: Path, *, duration_seconds: int = 300) -> None:
        if duration_seconds < 0:
            raise ValueError("Cooldown duration must not be negative")
        SQLiteWatchStore(path)
        self.path = path
        self.duration_seconds = duration_seconds

    def record_success(self, guild_id: int, channel_id: int, at: datetime) -> None:
        if min(guild_id, channel_id) < 1:
            raise ValueError("Guild and channel identifiers must be positive")
        when = _microseconds(at)
        expiry = _microseconds(at + timedelta(seconds=self.duration_seconds))
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO summary_cooldowns "
                    "(guild_id, channel_id, last_success_us, expires_at_us) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, channel_id) DO UPDATE SET "
                    "last_success_us=excluded.last_success_us, "
                    "expires_at_us=excluded.expires_at_us "
                    "WHERE excluded.last_success_us >= summary_cooldowns.last_success_us",
                    (guild_id, channel_id, when, expiry),
                )
        except sqlite3.Error as exc:
            raise CooldownStoreError("Cooldown write failed") from exc

    def remaining(self, guild_id: int, channel_id: int, now: datetime) -> int:
        if min(guild_id, channel_id) < 1:
            raise ValueError("Guild and channel identifiers must be positive")
        current = _microseconds(now)
        try:
            with sqlite3.connect(self.path, timeout=5) as connection:
                row = connection.execute(
                    "SELECT expires_at_us FROM summary_cooldowns "
                    "WHERE guild_id=? AND channel_id=?",
                    (guild_id, channel_id),
                ).fetchone()
        except sqlite3.Error as exc:
            raise CooldownStoreError("Cooldown read failed") from exc
        if row is None:
            return 0
        remaining = (_datetime(row[0]) - _datetime(current)).total_seconds()
        return min(self.duration_seconds, max(0, math.ceil(remaining)))


def cooldown_notice(remaining_seconds: int) -> str:
    if remaining_seconds < 1:
        raise ValueError("Remaining cooldown must be positive")
    minutes, seconds = divmod(remaining_seconds, 60)
    return f"🧊 아직은 때가 아니오. {minutes:02d}분 {seconds:02d}초 뒤에 오시오. ⏰"
