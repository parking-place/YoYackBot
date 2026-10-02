"""T120-P6-C: reply links stay honest across 1.2.0 → released 1.1.3a writes → 1.2.0 (LXC only).

Steps, in order, each with the matching interpreter:
  new-prepare DB, old-write DB (1.1.3a venv), new-verify DB.
Only synthetic IDs and counts are printed.
"""

import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

NOW = datetime.now(UTC).replace(microsecond=0)
BASE = 1_400_000_000_000_000_000


def mid(n: int) -> int:
    return BASE + n * 1_000_000


def links(path: Path) -> list[list[int]]:
    with closing(sqlite3.connect(path)) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")}
        rows = connection.execute(
            "SELECT message_id - ?, target_id - ? FROM message_reply_refs ORDER BY message_id",
            (BASE, BASE),
        ).fetchall() if "message_reply_refs" in tables else []
        return {
            "links": [[a // 1_000_000, b // 1_000_000] for a, b in rows],
            "trigger": "message_reply_refs_cleanup" in tables,
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "messages": connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        }


def record(n: int, *, to: int | None = None, minutes_ago: int = 60, **extra):
    from yoyackbot.domain import MessageRecord

    if to is not None:
        extra["reply_to_message_id"] = mid(to)
    return MessageRecord(
        mid(n), 1, 99, 1 + n % 2, "합성 화자", f"합성 {n}", NOW - timedelta(minutes=minutes_ago - n),
        is_reply=to is not None or extra.pop("reply", False), **extra,
    )


def new_prepare(path: Path) -> dict:
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path).replace(1, frozenset({99}))
    store = SQLiteMessageStore(path)
    for item in (record(1), record(2, to=1), record(3, to=2), record(4), record(5, to=4)):
        store.upsert(item, cached_at=NOW)
    return links(path)


def old_write(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.domain import MessageRecord
    from yoyackbot.message_store import SQLiteMessageStore

    assert __version__ == "1.1.3.1", __version__
    store = SQLiteMessageStore(path)
    store.delete_many(1, 99, {mid(1)})                         # target of 2 deleted by old code
    store.update_content(1, 99, mid(3), "합성 3 수정", edited_at=NOW, cached_at=NOW)
    store.upsert(MessageRecord(                                # old writer re-delivers reply 5
        mid(5), 1, 99, 2, "합성 화자", "합성 5", NOW - timedelta(minutes=55), is_reply=True,
    ), cached_at=NOW)
    store.upsert(MessageRecord(                                # a reply it cannot link
        mid(6), 1, 99, 1, "합성 화자", "합성 6", NOW - timedelta(minutes=54), is_reply=True,
    ), cached_at=NOW)
    return {"version": __version__, **links(path)}


def new_verify(path: Path) -> dict:
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path)
    store = SQLiteMessageStore(path)
    selected = store.recent(1, 99, NOW - timedelta(days=1), NOW)
    targets = {
        (item.message_id - BASE) // 1_000_000: (
            None if item.reply_to_message_id is None
            else (item.reply_to_message_id - BASE) // 1_000_000
        ) for item in selected if item.is_reply
    }
    SQLiteWatchStore(path).replace(1, frozenset())
    return {"reply_targets": targets, "after_unwatch": links(path)["links"], **links(path)}


if __name__ == "__main__":
    step, database = sys.argv[1], Path(sys.argv[2])
    result = {"new-prepare": new_prepare, "old-write": old_write, "new-verify": new_verify}[step](database)
    print(json.dumps({"step": step, **result}, sort_keys=True))
