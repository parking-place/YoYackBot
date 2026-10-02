"""T120-P7-B: an isolated DB goes 1.1.3a → 1.2.0 → 1.1.3a → 1.2.0, plus a clean 1.2.0 install.

Run each step with the matching interpreter (LXC only), in order:
  old-create DB, new-upgrade DB, old-ops DB, new-verify DB, new-fresh DIR
Old steps use the released 1.1.3a venv. Only synthetic IDs and counts are printed.
"""

import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

NOW = datetime.now(UTC).replace(microsecond=0)
BASE = 1_400_000_000_000_000_000


def mid(n: int) -> int:
    return BASE + n * 1_000_000


def facts(path: Path) -> dict:
    with closing(sqlite3.connect(path)) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")}

        def rows(sql: str) -> list:
            return [list(row) for row in connection.execute(sql)]

        return {
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "watched": rows("SELECT guild_id, channel_id FROM watched_channels ORDER BY 1, 2"),
            "messages": [(m - BASE) // 1_000_000 for (m,) in connection.execute(
                "SELECT message_id FROM messages ORDER BY message_id")],
            "links": [[(a - BASE) // 1_000_000, (b - BASE) // 1_000_000] for a, b in connection.execute(
                "SELECT message_id, target_id FROM message_reply_refs ORDER BY message_id")]
            if "message_reply_refs" in names else None,
            "progress": rows("SELECT guild_id, channel_id, COALESCE(pages, -1) FROM backfill_progress "
                             "ORDER BY 1, 2") if "backfill_progress" in names else None,
            "trigger": "message_reply_refs_cleanup" in names,
        }


def message(n: int, *, guild: int = 1, channel: int = 99, hours_ago: float = 1.0, **extra):
    from yoyackbot.domain import MessageRecord

    return MessageRecord(mid(n), guild, channel, 1 + n % 2, "합성 화자", f"합성 {n}",
                         NOW - timedelta(hours=hours_ago) + timedelta(minutes=n), **extra)


def backup_keys(path: Path) -> list[str]:
    from yoyackbot.settings_backup import backup_settings

    with tempfile.TemporaryDirectory() as directory:
        backup = backup_settings(path, Path(directory))
        text = backup.read_text()
        assert "합성" not in text and "reply" not in text and "progress" not in text
        return sorted(json.loads(text))


def old_create(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.1.3.1", __version__
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99, 98}))
    watches.replace(2, frozenset({77}))
    store = SQLiteMessageStore(path)
    for item in (message(1), message(2, is_reply=True), message(3, guild=2, channel=77)):
        store.upsert(item, cached_at=NOW)
    return {"version": __version__, **facts(path)}


def new_upgrade(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.backfill import SQLiteBackfillStore
    from yoyackbot.message_store import SQLiteMessageStore

    store = SQLiteMessageStore(path)
    backfills = SQLiteBackfillStore(path)
    backfills.ensure_existing()
    old_reply = store.recent(1, 99, NOW - timedelta(days=1), NOW)[1]
    for item in (message(4), message(5, is_reply=True, reply_to_message_id=mid(4)),
                 message(6, is_reply=True, reply_to_message_id=mid(5)),
                 message(7, hours_ago=24 * 40), message(8, channel=98),
                 message(9, channel=98, is_reply=True, reply_to_message_id=mid(8))):
        store.upsert(item, cached_at=NOW)
    return {"version": __version__, "old_reply_target": old_reply.reply_to_message_id,
            "backup_keys": backup_keys(path), **facts(path)}


def old_ops(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.1.3.1", __version__
    store = SQLiteMessageStore(path)
    store.update_content(1, 99, mid(6), "합성 6 수정", edited_at=NOW, cached_at=NOW)  # edit a reply
    store.delete_many(1, 99, {mid(4)})                       # delete a target
    store.prune_before(NOW - timedelta(days=30))              # retention (no-op on recent rows)
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))                       # unwatch 98 (reply 9 → 8)
    watches.remove_guild(2)                                   # leave Guild 2
    store.upsert(message(10, is_reply=True), cached_at=NOW)   # a reply it cannot link
    return {"version": __version__, **facts(path)}


def new_verify(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.backfill import SQLiteBackfillStore
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path)
    store = SQLiteMessageStore(path)
    store.upsert(message(4), cached_at=NOW)  # a stale page re-delivers the deleted target
    selected = store.recent(1, 99, NOW - timedelta(days=30), NOW + timedelta(hours=1))
    targets = {(item.message_id - BASE) // 1_000_000: (
        None if item.reply_to_message_id is None
        else (item.reply_to_message_id - BASE) // 1_000_000) for item in selected if item.is_reply}
    progress = SQLiteBackfillStore(path).progress_snapshot(1, 99, cutoff=NOW - timedelta(days=30))
    return {"version": __version__, "reply_targets": targets, "pages_99": progress.pages,
            "backup_keys": backup_keys(path), **facts(path)}


def new_fresh(directory: Path) -> dict:
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.settings_backup import backup_settings, restore_settings
    from yoyackbot.watch_store import SQLiteWatchStore

    path = directory / "fresh.db"
    SQLiteWatchStore(path).replace(1, frozenset({99}))
    SQLiteMessageStore(path).upsert(message(1), cached_at=NOW)
    backup = backup_settings(path, directory / "backups")
    restored = directory / "restored.db"
    restore_settings(backup, restored, live_database=path)
    SQLiteMessageStore(restored)
    return {"fresh": facts(path), "restored": facts(restored)}


if __name__ == "__main__":
    step, target = sys.argv[1], Path(sys.argv[2])
    run = {"old-create": old_create, "new-upgrade": new_upgrade, "old-ops": old_ops,
           "new-verify": new_verify, "new-fresh": new_fresh}[step]
    print(json.dumps({"step": step, **run(target)}, sort_keys=True, default=str))
