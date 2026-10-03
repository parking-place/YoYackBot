"""T131-P4: an isolated DB goes 1.3.0 → 1.3.1 → 1.3.0 → 1.3.1, plus a clean 1.3.1 install.

Old steps run with the 1.3.0 candidate venv, new steps with 1.3.1 `src`, in this order:
  old-create DB, new-upgrade DB, old-ops DB, new-verify DB, new-fresh DIR
Only synthetic IDs, counts and fixed texts are printed.
"""

import asyncio
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

        def rows(sql: str) -> list | None:
            return [list(r) for r in connection.execute(sql)] if sql.split(" FROM ")[1].split()[0] in names else None

        return {
            "user_version": connection.execute("PRAGMA user_version").fetchone()[0],
            "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
            "watched": rows("SELECT guild_id, channel_id FROM watched_channels ORDER BY 1, 2"),
            "summary_cooldowns": rows("SELECT guild_id, channel_id FROM summary_cooldowns ORDER BY 1, 2"),
            "idiom_cooldowns": rows("SELECT guild_id, channel_id FROM idiom_cooldowns ORDER BY 1, 2"),
            "fast": rows("SELECT guild_id FROM guild_fast_mode ORDER BY 1"),
            "tones": rows("SELECT guild_id FROM guild_tones ORDER BY 1"),
            "ratings": rows("SELECT guild_id, channel_id, COUNT(*) FROM recent_ratings GROUP BY 1, 2 ORDER BY 1, 2"),
        }


def old_create(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.cooldown import SQLiteCooldownStore
    from yoyackbot.domain import MessageRecord
    from yoyackbot.message_store import SQLiteMessageStore
    from yoyackbot.tone import SQLiteToneStore
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.3.0", __version__
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99, 98}))
    watches.replace(2, frozenset({77}))
    store = SQLiteMessageStore(path)
    for n, guild, channel in ((1, 1, 99), (2, 1, 98), (3, 2, 77)):
        store.upsert(MessageRecord(mid(n), guild, channel, 7, "합성 화자", f"합성 {n}",
                                   NOW - timedelta(minutes=10 - n)), cached_at=NOW)
    SQLiteCooldownStore(path, duration_seconds=300).record_success(1, 99, NOW)
    SQLiteToneStore(path).save(1, "보고서체로 쓰시오", expected_version=0)
    return {"version": __version__, **facts(path)}


def new_upgrade(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.cooldown import SQLiteCooldownStore
    from yoyackbot.settings_backup import backup_settings
    from yoyackbot.speed import SQLiteSpeedStore

    idioms = SQLiteCooldownStore(path, duration_seconds=300, table="idiom_cooldowns")
    for guild, channel in ((1, 99), (1, 98), (2, 77)):
        idioms.record_success(guild, channel, NOW)
    speeds = SQLiteSpeedStore(path)
    speeds.set(1, True)
    speeds.set(2, True)
    with tempfile.TemporaryDirectory() as directory:
        keys = sorted(json.loads(backup_settings(path, Path(directory)).read_text()))
    return {"version": __version__, "backup_keys": keys, **facts(path)}


def old_ops(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.watch_store import SQLiteWatchStore

    assert __version__ == "1.3.0", __version__
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))   # 1.3.0 leaves the (1, 98) idiom cooldown behind
    watches.remove_guild(2)               # and guild 2's idiom cooldown and fast-mode row
    return {"version": __version__, **facts(path)}


def new_verify(path: Path) -> dict:
    from yoyackbot import __version__
    from yoyackbot.cooldown import SQLiteCooldownStore
    from yoyackbot.speed import SQLiteSpeedStore
    from yoyackbot.state import AdmissionKind, ChannelStates, CooldownKind
    from yoyackbot.watch_store import SQLiteWatchStore

    SQLiteWatchStore(path)  # opening prunes idiom cooldowns of unwatched channels

    async def admissions() -> dict:
        states = ChannelStates(
            SQLiteCooldownStore(path, duration_seconds=300),
            idiom_cooldowns=SQLiteCooldownStore(path, duration_seconds=300, table="idiom_cooldowns"),
            clock=lambda: NOW + timedelta(seconds=60),
        )
        summary = await states.admit(1, 99)
        await states.finish(1, 99)
        idiom = await states.admit(1, 99, kind=CooldownKind.IDIOM)
        return {"summary": summary.kind.value, "summary_left": summary.remaining_seconds,
                "idiom": idiom.kind.value, "idiom_left": idiom.remaining_seconds,
                "both_cooldown": summary.kind is idiom.kind is AdmissionKind.COOLDOWN}

    speeds = SQLiteSpeedStore(path)
    return {"version": __version__, "admit_1_99": asyncio.run(admissions()),
            "fast_1": speeds.fast(1), "fast_2": speeds.fast(2), **facts(path)}


def new_fresh(directory: Path) -> dict:
    from yoyackbot.cooldown import SQLiteCooldownStore
    from yoyackbot.settings_backup import backup_settings, restore_settings
    from yoyackbot.speed import SQLiteSpeedStore
    from yoyackbot.watch_store import SQLiteWatchStore

    path = directory / "fresh.db"
    SQLiteWatchStore(path).replace(1, frozenset({99}))
    SQLiteSpeedStore(path).set(1, True)
    SQLiteCooldownStore(path, table="idiom_cooldowns").record_success(1, 99, NOW)
    backup = backup_settings(path, directory / "backups")
    restored = directory / "restored.db"
    restore_settings(backup, restored, live_database=path)
    return {"fresh": facts(path), "restored": facts(restored)}


if __name__ == "__main__":
    step, target = sys.argv[1], Path(sys.argv[2])
    run = {"old-create": old_create, "new-upgrade": new_upgrade, "old-ops": old_ops,
           "new-verify": new_verify, "new-fresh": new_fresh}[step]
    print(json.dumps({"step": step, **run(target)}, sort_keys=True, default=str))
