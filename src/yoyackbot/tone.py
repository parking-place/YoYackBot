"""1.3.0 `/말투`: one server's tone and personality text, stored in an optional table."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from yoyackbot.channel_config import ConcurrentUpdate
from yoyackbot.summary_prompt import TONE_LIMIT
from yoyackbot.watch_store import SQLiteWatchStore


class ToneTooLong(ValueError):
    """Only length is checked (user decision): empty or over the limit is refused."""


def clean_tone(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").strip()
    if not cleaned or len(cleaned) > TONE_LIMIT:
        raise ToneTooLong("Tone must be 1..1500 characters")
    return cleaned


class SQLiteToneStore:
    """(version, text) per server; text None means the default tone. Included in backups."""

    def __init__(self, path: Path) -> None:
        SQLiteWatchStore(path)
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA secure_delete=ON")
            yield connection
        finally:
            connection.close()

    def snapshot(self, guild_id: int) -> tuple[int, str | None]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT version, content FROM guild_tones WHERE guild_id=?", (guild_id,)
            ).fetchone()
        return (row[0], row[1]) if row is not None else (0, None)

    def get(self, guild_id: int) -> str | None:
        return self.snapshot(guild_id)[1]

    def save(self, guild_id: int, text: str | None, *, expected_version: int) -> int:
        """Set (or with None, reset) the tone if nobody changed it since the view opened."""
        content = None if text is None else clean_tone(text)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version FROM guild_tones WHERE guild_id=?", (guild_id,)
            ).fetchone()
            version = row[0] if row is not None else 0
            if version != expected_version:
                raise ConcurrentUpdate("Tone changed while the view was open")
            connection.execute(
                "INSERT INTO guild_tones (guild_id, content, version, updated_us) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET content=excluded.content, "
                "version=excluded.version, updated_us=excluded.updated_us",
                (guild_id, content, version + 1, _now_us()),
            )
            return version + 1

    def remove_guild(self, guild_id: int) -> None:
        with self._connection() as connection, connection:
            connection.execute("DELETE FROM guild_tones WHERE guild_id=?", (guild_id,))


def _now_us() -> int:
    delta = datetime.now(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
