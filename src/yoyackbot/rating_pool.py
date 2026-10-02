"""1.3.0: ten rating candidates, code filters, the judge's answer, and recent posted ratings."""

import re
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.output_quality import (
    RATING_LABEL,
    narrator_mocks_ongoing,
    narrator_uses_hate_term,
    rating_issue,
)
from yoyackbot.watch_store import SQLiteWatchStore

MAX_CANDIDATES = 10
RECENT_LIMIT = 20
MAX_RATING_CHARS = 160

_CANDIDATE = re.compile(
    r"^\s*(?:\d{1,2}\s*[.)\]:\-]\s*|[-*•]\s+)?(?:\*\*)?요약창섭의 떡밥 한줄 평가(?:\*\*)?\s*[:：]\s*(.+?)\s*$"
)
# The model sometimes drops the label but keeps the numbering; the filters still apply.
_NUMBERED = re.compile(r"^\s*\d{1,2}\s*[.)\]]\s+(?!\**요약창섭)(.+?)\s*$")
# Topic hopping, clutter and bustle are the overused angle (1.3.0); city 부산 alone is a topic word.
BANNED = re.compile(
    r"튀[어는고었며니]|튄|왔다\s*갔다|오락가락|이리저리|정신\s*(?:없|사납)|부산[하스해한떨]|요란|"
    r"한\s*상|뒤엉|뒤죽박죽|중구난방|어수선|산만|화제\s*(?:가|를)?\s*(?:바뀌|전환|돌)"
)
_DIGIT = re.compile(r"[0-9０-９]")
_SIMILAR = re.compile(r"^\s*비슷함\s*:\s*(.*?)\s*$")
_CHOICE = re.compile(r"^\s*선택\s*:\s*(.*?)\s*$")


def parse_candidates(text: str) -> list[str]:
    """Normalized `label : content` lines in order, without duplicates, at most ten."""
    found: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = _CANDIDATE.match(line) or _NUMBERED.match(line)
        if match is None:
            continue
        content = match.group(1).strip()
        key = re.sub(r"\s+", " ", content)
        if not content or key in seen:
            continue
        seen.add(key)
        found.append(RATING_LABEL + content)
        if len(found) == MAX_CANDIDATES:
            break
    return found


def banned_angle(rating: str) -> bool:
    return bool(BANNED.search(rating.removeprefix(RATING_LABEL)))


def usable_rating(
    rating: str, source_bodies: Sequence[str], names: Sequence[str],
    message_keys: frozenset[str] = frozenset(),
) -> bool:
    """A rating line names no one, has no numbers, no banned angle, sneer or slur."""
    content = rating.removeprefix(RATING_LABEL)
    if (
        not content.strip() or len(content) > MAX_RATING_CHARS or "\n" in content
        or not any("가" <= char <= "힣" for char in content)
    ):
        return False
    if banned_angle(rating) or _DIGIT.search(content):
        return False
    if any(len(name) >= 2 and name in content for name in names):
        return False
    if narrator_uses_hate_term(rating) or narrator_mocks_ongoing(rating):
        return False
    return rating_issue(rating, source_bodies, message_keys) is None


def filter_candidates(
    candidates: Sequence[str], source_bodies: Sequence[str], names: Sequence[str],
    message_keys: frozenset[str] = frozenset(),
) -> list[str]:
    return [item for item in candidates if usable_rating(item, source_bodies, names, message_keys)]


def parse_judgement(text: str, count: int) -> tuple[frozenset[int], int | None] | None:
    """`비슷함: 번호들` / `선택: 번호`. None when the answer is malformed or contradicts itself."""
    similar_line = choice_line = None
    for line in text.strip().splitlines():
        if (match := _SIMILAR.match(line)) is not None and similar_line is None:
            similar_line = match.group(1)
        elif (match := _CHOICE.match(line)) is not None and choice_line is None:
            choice_line = match.group(1)
    if similar_line is None or choice_line is None:
        return None
    similar: set[int] = set()
    if similar_line not in ("없음", ""):
        for part in re.split(r"[,\s]+", similar_line):
            if not part:
                continue
            if not part.isdigit() or not 1 <= int(part) <= count:
                return None
            similar.add(int(part))
    if choice_line == "없음":
        return frozenset(similar), None
    if not choice_line.isdigit() or not 1 <= int(choice_line) <= count or int(choice_line) in similar:
        return None
    return frozenset(similar), int(choice_line)


class SQLiteRecentRatings:
    """Per-channel posted ratings: 20 newest within retention; not part of settings backups."""

    def __init__(
        self, path: Path, *, retention_days: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 1 <= retention_days <= 30:
            raise ValueError("Retention must be between 1 and 30 days")
        SQLiteWatchStore(path)
        self.path = path
        self.retention_days = retention_days
        self.clock = clock or (lambda: datetime.now(UTC))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            connection.execute("PRAGMA secure_delete=ON")
            yield connection
        finally:
            connection.close()

    def _cutoff_us(self) -> int:
        return _us(self.clock() - timedelta(days=self.retention_days))

    def recent(self, guild_id: int, channel_id: int) -> list[str]:
        """Newest first."""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT text FROM recent_ratings WHERE guild_id=? AND channel_id=? AND posted_us>=? "
                "ORDER BY posted_us DESC, rowid DESC LIMIT ?",
                (guild_id, channel_id, self._cutoff_us(), RECENT_LIMIT),
            ).fetchall()
        return [row[0] for row in rows]

    def add(self, guild_id: int, channel_id: int, text: str, *, posted_at: datetime) -> bool:
        """Remember a posted rating of a still-watched channel and keep only the newest 20."""
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            watched = connection.execute(
                "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
                (guild_id, channel_id),
            ).fetchone()
            if watched is None:
                return False
            connection.execute(
                "INSERT INTO recent_ratings (guild_id, channel_id, posted_us, text) VALUES (?, ?, ?, ?)",
                (guild_id, channel_id, _us(posted_at), text),
            )
            connection.execute(
                "DELETE FROM recent_ratings WHERE guild_id=? AND channel_id=? AND (posted_us<? OR "
                "rowid NOT IN (SELECT rowid FROM recent_ratings WHERE guild_id=? AND channel_id=? "
                "ORDER BY posted_us DESC, rowid DESC LIMIT ?))",
                (guild_id, channel_id, self._cutoff_us(), guild_id, channel_id, RECENT_LIMIT),
            )
            return True

    def prune(self) -> int:
        with self._connection() as connection, connection:
            return connection.execute(
                "DELETE FROM recent_ratings WHERE posted_us<?", (self._cutoff_us(),)
            ).rowcount


def _us(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
