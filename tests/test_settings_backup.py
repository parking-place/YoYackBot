"""Recovery preserves settings while deliberately discarding raw conversations."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.collection import CollectionCoordinator
from yoyackbot.count_collection import CountCollector
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind
from yoyackbot.history import HistoryResult
from yoyackbot.long_range import LongRangeCollector
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.range_collection import TimeRangeCollector
from yoyackbot.settings_backup import BackupError, backup_settings, restore_settings
from yoyackbot.watch_store import SQLiteWatchStore


def test_settings_only_restore_keeps_watches_and_refetches_allowed_history(tmp_path) -> None:
    now = datetime.now(UTC)
    original = tmp_path / "live.db"
    watches = SQLiteWatchStore(original)
    watches.replace(1, frozenset({10}))
    record = MessageRecord(100, 1, 10, 3, "가람", "PRIVATE_RAW_CONVERSATION", now - timedelta(minutes=5))
    SQLiteMessageStore(original).upsert(record, cached_at=now)
    with sqlite3.connect(original) as connection:
        connection.execute(
            "INSERT INTO summary_cooldowns VALUES (?, ?, ?, ?)",
            (1, 10, 1_000_000, 301_000_000),
        )
    backup = backup_settings(original, tmp_path / "backups")
    assert backup.stat().st_mode & 0o777 == 0o600
    assert json.loads(backup.read_text())["schema"] == 5
    assert "PRIVATE_RAW_CONVERSATION" not in backup.read_text()
    restored = tmp_path / "isolated" / "restored.db"
    restore_settings(backup, restored, live_database=original)
    assert SQLiteWatchStore(restored).get(1) == frozenset({10})
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT COUNT(*) FROM summary_cooldowns").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM coverage").fetchone()[0] == 0
    with sqlite3.connect(original) as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1

    class History:
        async def collect(self, *_args, **_kwargs):
            return HistoryResult((record,), 1, True)

    async def recollect() -> None:
        history = History()
        store = SQLiteMessageStore(restored)
        watch_store = SQLiteWatchStore(restored)
        recent = TimeRangeCollector(store, watch_store, history, clock=lambda: now)
        coordinator = CollectionCoordinator(
            watch_store, LongRangeCollector(recent, history), CountCollector(recent, history),
            history,
        )
        outcome = await coordinator.collect(
            SimpleNamespace(id=10, guild=SimpleNamespace(id=1), type=discord.ChannelType.text),
            guild_id=1, channel_id=10,
            request=RangeRequest(RequestKind.TIME, now, start=now - timedelta(hours=1)),
        )
        assert (outcome.cache_count, outcome.history_count) == (0, 1)
        assert len(outcome.messages) == 1

    asyncio.run(recollect())


def test_restore_refuses_live_or_existing_target_and_invalid_backup(tmp_path) -> None:
    live = tmp_path / "live.db"
    SQLiteWatchStore(live)
    backup = backup_settings(live, tmp_path / "backups")
    with pytest.raises(BackupError):
        restore_settings(backup, live, live_database=live)
    existing = tmp_path / "existing.db"
    existing.write_text("keep me")
    with pytest.raises(BackupError):
        restore_settings(backup, existing, live_database=live)
    assert existing.read_text() == "keep me"
    broken = tmp_path / "broken.json"
    broken.write_text('{"format":"wrong","schema":5}')
    broken.chmod(0o600)
    with pytest.raises(BackupError):
        restore_settings(broken, tmp_path / "new.db", live_database=live)
    assert not (tmp_path / "new.db").exists()
