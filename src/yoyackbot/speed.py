"""1.3.1 `/속도 설정`: whether a server asked for the fast service tier (off by default)."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from yoyackbot.watch_store import SQLiteWatchStore


class SQLiteSpeedStore:
    """A row in the optional `guild_fast_mode` table means on. Included in backups."""

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

    def fast(self, guild_id: int) -> bool:
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM guild_fast_mode WHERE guild_id=?", (guild_id,)
            ).fetchone() is not None

    def set(self, guild_id: int, fast: bool) -> None:
        """Turning on or off twice gives the same result, so no revision check is needed."""
        if guild_id < 1:
            raise ValueError("Guild identifier must be positive")
        with self._connection() as connection, connection:
            if fast:
                connection.execute(
                    "INSERT INTO guild_fast_mode (guild_id, updated_us) VALUES (?, ?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET updated_us=excluded.updated_us",
                    (guild_id, _now_us()),
                )
            else:
                connection.execute("DELETE FROM guild_fast_mode WHERE guild_id=?", (guild_id,))


def _now_us() -> int:
    delta = datetime.now(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
