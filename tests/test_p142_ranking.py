"""1.4.2-P1: timeout records and `/처형순위` (T142-P1-A/B)."""

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from test_p140_audit_log import BOT, CALLER, MOD, TARGET, client_with, entry
from test_p140_tone_notices import table_for, toned

from yoyackbot.execution import SQLiteExecutionStore
from yoyackbot.execution_log import timeout_event
from yoyackbot.execution_ranking import (
    READ_FAILED,
    dead_text,
    install_ranking_command,
    period_start,
    ranking_message,
)
from yoyackbot.notices import BOOK, localize, unmatched
from yoyackbot.settings_backup import backup_settings
from yoyackbot.watch_store import SQLiteWatchStore

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 7, 21, tzinfo=UTC)           # Thursday 2026-10-08 06:00 KST


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


def store_at(tmp_path):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path)
    return path, SQLiteExecutionStore(path)


# T142-P1-A ------------------------------------------------------------------------------

def test_dead_time_of_each_change() -> None:
    at = entry(None, None).created_at
    assert timeout_event(entry(None, at + timedelta(minutes=10))).seconds() == 600
    assert timeout_event(entry(at - timedelta(minutes=1), at + timedelta(minutes=10))).seconds() == 600
    assert timeout_event(entry(at + timedelta(minutes=5), at + timedelta(hours=1))).seconds() == 3300
    assert timeout_event(entry(at + timedelta(minutes=3), None)).seconds() == -180


def test_every_timeout_is_recorded_without_reason_or_log_channel(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client, home, log_channel = client_with(tmp_path, monkeypatch, channel=None)
    client.remember_execution(1, TARGET, CALLER)
    at = entry(None, None).created_at

    async def scenario():
        try:
            await client.on_audit_log_entry_create(
                entry(None, at + timedelta(minutes=10), guild=home, user_id=BOT, reason="비밀 사유"))
            await client.on_audit_log_entry_create(
                entry(at + timedelta(minutes=10), at + timedelta(minutes=30), guild=home))
            await client.on_audit_log_entry_create(
                entry(at + timedelta(minutes=30), None, guild=home, user_id=BOT))
        finally:
            await client.close()

    asyncio.run(scenario())
    log_channel.send.assert_not_awaited()                       # no log channel, still recorded
    with sqlite3.connect(client.settings.database_path) as connection:
        rows = connection.execute(
            "SELECT kind, target_id, executor_id, seconds FROM execution_events ORDER BY rowid"
        ).fetchall()
        columns = [row[1] for row in connection.execute("PRAGMA table_info(execution_events)")]
    assert rows == [("apply", TARGET, CALLER, 600), ("extend", TARGET, MOD, 1200),
                    ("release", TARGET, BOT, -1800)]
    assert "reason" not in columns and "비밀 사유" not in caplog.text


def test_old_records_and_left_servers_are_cleaned(tmp_path) -> None:
    path, store = store_at(tmp_path)
    store.record(1, "apply", TARGET, MOD, 60, NOW - timedelta(days=41))
    store.record(2, "apply", TARGET, MOD, 60, NOW - timedelta(days=39))
    store.record(1, "apply", TARGET, MOD, 60, NOW)                    # prunes the 41-day-old one
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 2
    assert store.keep_only([1]) == 1
    SQLiteWatchStore(path).remove_guild(1)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM execution_events").fetchone()[0] == 0


def test_records_stay_out_of_the_settings_backup(tmp_path) -> None:
    path, store = store_at(tmp_path)
    store.record(1, "apply", 777001, 777002, 60, NOW)
    data = json.loads(backup_settings(path, tmp_path / "backups").read_text())
    assert "execution_events" not in data and "777001" not in json.dumps(data)


# T142-P1-B ------------------------------------------------------------------------------

def test_periods_follow_the_kst_calendar() -> None:
    assert period_start("day", NOW, KST) == datetime(2026, 10, 8, tzinfo=KST)
    assert period_start("week", NOW, KST) == datetime(2026, 10, 5, tzinfo=KST)       # Monday
    assert period_start("month", NOW, KST) == datetime(2026, 10, 1, tzinfo=KST)
    sunday_night = datetime(2026, 10, 11, 14, 59, tzinfo=UTC)                      # Sun 23:59 KST
    assert period_start("week", sunday_night, KST) == datetime(2026, 10, 5, tzinfo=KST)
    assert period_start("week", sunday_night + timedelta(minutes=1), KST) == datetime(2026, 10, 12, tzinfo=KST)


def test_ranking_order_ties_top_five_and_period(tmp_path) -> None:
    _path, store = store_at(tmp_path)
    today = period_start("day", NOW, KST)
    for target, times, seconds in ((11, 3, 60), (12, 3, 600), (13, 1, 30), (14, 2, 10), (15, 1, 5),
                                   (16, 1, 1)):
        for _ in range(times):
            store.record(1, "apply", target, 21 if target != 16 else 22, seconds, today + timedelta(hours=1))
    store.record(1, "release", 12, 21, -500, today + timedelta(hours=2))
    store.record(1, "apply", 99, None, 60, today + timedelta(hours=2))              # unknown executor
    store.record(1, "apply", 98, 21, 60, today - timedelta(minutes=1))              # yesterday
    store.record(2, "apply", 97, 21, 60, today + timedelta(hours=1))                # another server
    day = store.ranking(1, today, NOW + timedelta(seconds=1))
    assert day.victims == [(12, 3, 1300), (11, 3, 180), (14, 2, 20), (99, 1, 60), (13, 1, 30)]
    assert day.executioners == [(21, 10), (22, 1)] and day.total == 12
    week = store.ranking(1, period_start("week", NOW, KST), NOW + timedelta(seconds=1))
    assert week.total == 13 and (98, 1, 60) in store.ranking(1, today - timedelta(days=1), NOW, top=10).victims


def test_message_format_and_peace() -> None:
    from yoyackbot.execution import Ranking
    text = ranking_message("week", Ranking([(11, 3, 4800), (12, 1, 0), (13, 1, 30), (14, 1, 5)],
                                           [(21, 4)], 6))
    assert text == ("🏆 **이번 주 처형 순위**\n\n☠️ **단골 시체**\n"
                    "🥇 <@11> — 3회, ⏳1시간 20분\n🥈 <@12> — 1회, ⏳0초\n🥉 <@13> — 1회, ⏳30초\n"
                    "4. <@14> — 1회, ⏳5초\n\n🗡️ **처형 장인**\n🥇 <@21> — 4회\n\n"
                    "⚔️ 이 기간 처형은 모두 6건이오.")
    assert ranking_message("day", Ranking([], [], 0)) == "🏆 **오늘의 처형 순위**\n\n🕊️ 오늘은 처형이 없었소. 평화로웠구려."
    lonely = ranking_message("month", Ranking([(11, 1, 60)], [], 1))
    assert "🤷 누가 처형했는지 확인된 기록이 없소." in lonely
    assert dead_text(90061) == "1일 1시간"
    for sample in (text, lonely, *(ranking_message(p, Ranking([], [], 0)) for p in ("day", "week", "month")),
                   READ_FAILED):
        assert [line for line in unmatched(sample) if line] == [], sample


def test_the_command_answers_everyone_without_pings(tmp_path, monkeypatch) -> None:
    client, _home, _channel = client_with(tmp_path, monkeypatch)
    command = client.tree.get_command("처형순위")
    assert command.guild_only and command.default_permissions is None
    assert [p.name for p in command.parameters] == ["기간"]
    assert [c.name for c in command.parameters[0].choices] == ["일간", "주간", "월간"]
    asyncio.run(client.close())
    tmp_path = tmp_path / "ranking"
    tmp_path.mkdir()
    _path, store = store_at(tmp_path)
    store.record(1, "apply", 11, 21, 600, NOW - timedelta(hours=1))
    tree = SimpleNamespace(added=[])
    tree.add_command = tree.added.append
    install_ranking_command(tree, store, KST, clock=lambda: NOW)
    callback = tree.added[0].callback
    BOOK.set(1, table_for())
    for guild_id, expected in ((1, toned("🏆 **오늘의 처형 순위**")), (2, "🏆 **오늘의 처형 순위**")):
        asked = SimpleNamespace(guild_id=guild_id, response=SimpleNamespace(send_message=AsyncMock()))
        asyncio.run(callback(asked))
        sent = asked.response.send_message.await_args
        assert sent.args[0].split("\n")[0] == expected and "ephemeral" not in sent.kwargs
        mentions = sent.kwargs["allowed_mentions"]
        assert not mentions.users and not mentions.roles and not mentions.everyone
    assert "<@11> — 1회" in localize(2, ranking_message("day", store.ranking(1, period_start("day", NOW, KST), NOW)))


def test_unreadable_records_answer_only_the_caller(tmp_path) -> None:
    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("locked")

    tree = SimpleNamespace(added=[])
    tree.add_command = tree.added.append
    install_ranking_command(tree, SimpleNamespace(ranking=broken), KST, clock=lambda: NOW)
    asked = SimpleNamespace(guild_id=1, response=SimpleNamespace(send_message=AsyncMock()))
    asyncio.run(tree.added[0].callback(asked, "월간"))
    sent = asked.response.send_message.await_args
    assert sent.args[0] == READ_FAILED and sent.kwargs["ephemeral"] is True
