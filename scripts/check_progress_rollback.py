"""T120-P5-D: an isolated DB moves 1.2.0 → released 1.1.3a → 1.2.0 with progress kept honest.

Run the `new` and `old` steps with the matching interpreter (LXC only), in order:
  new-prepare DB, old-write DB (with the 1.1.3a venv), new-verify DB.
Only synthetic IDs and counts are printed.
"""

import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

GUILD = 1


def counts(path: Path) -> dict:
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        progress = (
            dict(connection.execute(
                "SELECT channel_id, COALESCE(pages, -1) FROM backfill_progress ORDER BY channel_id"
            ).fetchall()) if "backfill_progress" in tables else None
        )
        return {
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "watched": [row[0] for row in connection.execute(
                "SELECT channel_id FROM watched_channels ORDER BY channel_id")],
            "progress_pages": progress,
        }


def new_prepare(path: Path) -> dict:
    from yoyackbot.backfill import SQLiteBackfillStore
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path).replace(GUILD, frozenset({97, 98, 99}))
    store = SQLiteBackfillStore(path)
    for channel_id in (98, 99):
        state = store.get(GUILD, channel_id)
        assert store.save_page(
            state, (), next_cursor=state.cursor - 1_000, next_phase="history", finished_at=None,
            cached_at=datetime.now(UTC),
        )
    return counts(path)


def old_write(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.backfill import SQLiteBackfillStore
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.1.3.1", __version__
    watches = SQLiteWatchStore(path)
    watches.replace(GUILD, frozenset({98, 99, 96}))  # unwatch 97, watch 96 without progress
    store = SQLiteBackfillStore(path)
    state = store.get(GUILD, 98)
    assert store.save_page(  # the old writer advances 98's cursor without counting
        state, (), next_cursor=state.cursor - 1_000, next_phase="history", finished_at=None,
        cached_at=datetime.now(UTC),
    )
    return {"version": __version__, **counts(path)}


def new_verify(path: Path) -> dict:
    from yoyackbot.backfill import SQLiteBackfillStore
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path)
    store = SQLiteBackfillStore(path)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    pages = {
        channel_id: store.progress_snapshot(GUILD, channel_id, cutoff=cutoff).pages
        for channel_id in (96, 98, 99)
    }
    state = store.get(GUILD, 99)
    assert store.save_page(
        state, (), next_cursor=state.cursor - 1_000, next_phase="history", finished_at=None,
        cached_at=datetime.now(UTC),
    )
    pages_after = store.progress_snapshot(GUILD, 99, cutoff=cutoff).pages
    return {"snapshot_pages": pages, "99_after_new_page": pages_after, **counts(path)}


if __name__ == "__main__":
    step, database = sys.argv[1], Path(sys.argv[2])
    result = {"new-prepare": new_prepare, "old-write": old_write, "new-verify": new_verify}[step](database)
    print(json.dumps({"step": step, **result}, sort_keys=True))
