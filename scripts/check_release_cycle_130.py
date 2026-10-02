"""T130-P7: an isolated DB goes 1.2.0 → 1.3.0 → 1.2.0 → 1.3.0, plus a clean 1.3.0 install.

Old steps run with the 1.2.0 candidate venv, new steps with 1.3.0 `src`, in this order:
  old-create DB, new-upgrade DB, old-ops DB, new-verify DB, new-fresh DIR
Only synthetic IDs, counts and fixed texts are printed.
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
LABEL = "**요약창섭의 떡밥 한줄 평가** : "


def mid(n: int) -> int:
    return BASE + n * 1_000_000


def facts(path: Path) -> dict:
    with closing(sqlite3.connect(path)) as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')")}

        def rows(sql: str) -> list | None:
            return [list(r) for r in connection.execute(sql)] if sql.split(" FROM ")[1].split()[0] in names else None

        return {
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "watched": rows("SELECT guild_id, channel_id FROM watched_channels ORDER BY 1, 2"),
            "messages": [(m - BASE) // 1_000_000 for (m,) in connection.execute(
                "SELECT message_id FROM messages ORDER BY message_id")],
            "links": [[(a - BASE) // 1_000_000, (b - BASE) // 1_000_000] for a, b in connection.execute(
                "SELECT message_id, target_id FROM message_reply_refs ORDER BY message_id")],
            "ratings": rows("SELECT guild_id, channel_id, COUNT(*) FROM recent_ratings GROUP BY 1, 2 ORDER BY 1, 2"),
            "tones": rows("SELECT guild_id, version, content IS NOT NULL FROM guild_tones ORDER BY 1"),
        }


def message(n: int, *, guild: int = 1, channel: int = 99, content: str | None = None, **extra):
    from yoyackbot.domain import MessageRecord

    return MessageRecord(mid(n), guild, channel, 1 + n % 2, "합성 화자", content or f"합성 {n}",
                         NOW - timedelta(hours=1) + timedelta(minutes=n), **extra)


def old_create(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.2.0", __version__
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99, 98}))
    watches.replace(2, frozenset({77}))
    store = SQLiteMessageStore(path)
    for item in (message(1), message(2, is_reply=True, reply_to_message_id=mid(1)),
                 message(3, guild=2, channel=77), message(4, channel=98)):
        store.upsert(item, cached_at=NOW)
    return {"version": __version__, **facts(path)}


def new_upgrade(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.rating_pool import SQLiteRecentRatings
    from yoyackbot.settings_backup import backup_settings
    from yoyackbot.tone import SQLiteToneStore

    tones = SQLiteToneStore(path)
    tones.save(1, "보고서체로 쓰시오", expected_version=0)
    tones.save(2, "짧게 쓰시오", expected_version=0)
    ratings = SQLiteRecentRatings(path)
    for guild, channel in ((1, 99), (1, 98), (2, 77)):
        ratings.add(guild, channel, LABEL + "합성 평가이오", posted_at=NOW)
    with tempfile.TemporaryDirectory() as directory:
        keys = sorted(json.loads(backup_settings(path, Path(directory)).read_text()))
    return {"version": __version__, "backup_keys": keys, **facts(path)}


def old_ops(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.2.0", __version__
    store = SQLiteMessageStore(path)
    store.update_content(1, 99, mid(2), "합성 2 수정", edited_at=NOW, cached_at=NOW)
    store.delete_many(1, 99, {mid(1)})
    store.prune_before(NOW - timedelta(days=30))
    store.upsert(message(5, content="!!말하자면"), cached_at=NOW)   # 1.2.0 caches it as chat
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    watches.remove_guild(2)
    return {"version": __version__, **facts(path)}


def new_verify(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.rating_pool import SQLiteRecentRatings
    from yoyackbot.tone import SQLiteToneStore
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path)
    store = SQLiteMessageStore(path)
    latest = store.latest(1, 99, NOW - timedelta(days=1), NOW + timedelta(hours=1), 30)
    return {
        "version": __version__,
        "latest_ids": [(row.message_id - BASE) // 1_000_000 for row in latest],
        "tone_1": SQLiteToneStore(path).get(1) is not None,
        "ratings_99": len(SQLiteRecentRatings(path).recent(1, 99)),
        **facts(path),
    }


def new_fresh(directory: Path) -> dict:
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.settings_backup import backup_settings, restore_settings
    from yoyackbot.tone import SQLiteToneStore
    from yoyackbot.watch_store import SQLiteWatchStore

    path = directory / "fresh.db"
    SQLiteWatchStore(path).replace(1, frozenset({99}))
    SQLiteMessageStore(path).upsert(message(1), cached_at=NOW)
    SQLiteToneStore(path).save(1, "보고서체로 쓰시오", expected_version=0)
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
