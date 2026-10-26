"""1.4.4-P1: exercise channel/role settings and the daily/weekly stores (T144-P1-A/B)."""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands
from test_p140_execution_settings import opened_view, pick, press, said
from test_role_config import OTHER, ROLE, guild, interaction

from yoyackbot.channel_config import NOT_ALLOWED, SLASH_PERMISSIONS
from yoyackbot.diet import DailyRecord, SQLiteDietStore
from yoyackbot.diet_config import (
    EXERCISE_SCHEDULE,
    DietView,
    exercise_message,
    install_diet_settings,
)
from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.notices import unmatched
from yoyackbot.settings_backup import backup_settings, restore_settings
from yoyackbot.watch_store import SQLiteWatchStore

MANAGER = OTHER
NOW = datetime(2026, 10, 26, 13, tzinfo=UTC)


def setup(tmp_path):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({10}))
    store = SQLiteDietStore(path)
    roles = MemoryManagerRoleStore()
    roles.replace(1, frozenset({MANAGER}), expected_version=0)
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    install_diet_settings(tree, store, roles)
    return path, store, tree


# T144-P1-A ------------------------------------------------------------------------------

def test_defaults_follow_the_diet_settings(tmp_path) -> None:
    _path, store, _tree = setup(tmp_path)
    store.set_channel(1, 10)
    store.set_role(1, ROLE)
    assert store.exercise_settings(1) == (None, None) and store.exercise_target(1) == (10, ROLE)
    store.set_exercise_channel(1, 20)
    assert store.exercise_target(1) == (20, ROLE)
    store.set_exercise_role(1, OTHER)
    assert store.exercise_target(1) == (20, OTHER) and store.settings(1) == (10, ROLE)
    store.set_exercise_channel(1, None)
    store.set_exercise_role(1, None)
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM exercise_settings").fetchone()[0] == 0


def test_exercise_commands_and_screens(tmp_path) -> None:
    _path, store, tree = setup(tmp_path)
    for name in ("운동채널", "운동역할"):
        group = tree.get_command(name)
        assert group.guild_only and group.default_permissions == SLASH_PERMISSIONS
        assert getattr(group.get_command("설정").callback, "__yoyack_gated__", False)
    home = guild()

    async def scenario():
        nobody = interaction(home=home)
        await tree.get_command("운동채널").get_command("설정").callback(nobody)
        assert said(nobody) == NOT_ALLOWED
        manager = interaction(home=home, roles=(MANAGER,))
        await tree.get_command("운동채널").get_command("설정").callback(manager)
        view = opened_view(manager)
        assert isinstance(view, DietView) and view.section == "exercise"
        opened = manager.edit_original_response.await_args.kwargs["content"]
        assert opened.startswith("🏃 운동 채널: 없음(식단 채널을 씀)\n🏃 운동 역할: 없음(돼지역할을 씀)")
        assert EXERCISE_SCHEDULE in opened
        await pick(view, discord.ui.ChannelSelect, [SimpleNamespace(id=10)], manager)
        await press(view, "저장", manager)
        assert store.exercise_settings(1) == (10, None) and store.settings(1) == (None, None)
        admin = interaction(home=home, admin=True)
        await tree.get_command("운동역할").get_command("설정").callback(admin)
        roles_view = opened_view(admin)
        await pick(roles_view, discord.ui.RoleSelect, [SimpleNamespace(id=ROLE)], admin)
        await press(roles_view, "저장", admin)
        assert store.exercise_settings(1) == (10, ROLE)
        again = interaction(home=home, admin=True)
        await tree.get_command("운동역할").get_command("설정").callback(again)
        clearing = opened_view(again)
        await press(clearing, "해제", again)
        assert said(again).startswith("🧹 운동 역할을 비웠소(돼지역할을 씀)")
        await press(clearing, "저장", again)
        assert store.exercise_settings(1) == (10, None)

    asyncio.run(scenario())


def test_backup_and_cleanup(tmp_path) -> None:
    path, store, _tree = setup(tmp_path)
    store.set_exercise_channel(1, 20)
    store.set_exercise_role(2, ROLE)
    data = json.loads(backup_settings(path, tmp_path / "backups").read_text())
    assert sorted(row[:3] for row in data["exercise"]) == [[1, 20, None], [2, None, ROLE]]
    restored = tmp_path / "restored.sqlite"
    restore_settings(backup_settings(path, tmp_path / "backups"), restored, live_database=path)
    assert SQLiteDietStore(restored).exercise_settings(1) == (20, None)
    assert store.remove_channel(1, 20) and store.exercise_settings(1) == (None, None)
    assert store.remove_role(2, ROLE) and store.exercise_settings(2) == (None, None)


# T144-P1-B ------------------------------------------------------------------------------

def test_daily_records_and_week(tmp_path) -> None:
    path, store, _tree = setup(tmp_path)
    store.save_daily(1, "2026-10-20", [DailyRecord(501, 60, 20, "닭가슴살 샐러드", "러닝 30분"),
                                      DailyRecord(502, None, 80, "케이크", None)], NOW)
    store.save_daily(1, "2026-10-21", [DailyRecord(501, 70, 10, "계란", None)], NOW)
    store.save_daily(1, "2026-10-20", [DailyRecord(501, 65, 25, "닭가슴살" + "가" * 200, "러닝" + "나" * 200)], NOW)
    store.save_daily(2, "2026-10-20", [DailyRecord(503, 10, 10, "라면", None)], NOW)
    week = store.week(1, "2026-10-19", "2026-10-25")
    assert [day for day, _ in week[501]] == ["2026-10-20", "2026-10-21"]
    first = week[501][0][1]
    assert (first.protein_g, first.sugar_g, len(first.foods), len(first.exercise)) == (65, 25, 80, 80)
    assert week[502][0][1].protein_g is None and 503 not in week
    with pytest.raises(sqlite3.IntegrityError):
        store.save_daily(1, "2026-10-22", [DailyRecord(501, 401, 0, "말이 안 되는 양", None)], NOW)
    store.save_daily(1, "2026-12-15", [DailyRecord(501, 1, 1, "나중", None)], NOW + timedelta(days=50))
    assert store.week(1, "2026-10-19", "2026-10-25") == {}                # 40 days later: gone
    assert store.claim_week(1, "2026-10-19", "running", NOW) is True
    assert store.claim_week(1, "2026-10-19", "running", NOW) is False
    store.finish_week(1, "2026-10-19", "posted")
    assert store.week_done(1, "2026-10-19") == "posted" and store.week_done(1, "2026-10-26") is None
    data = json.loads(backup_settings(path, tmp_path / "backups").read_text())
    assert "diet_daily" not in json.dumps(data) and "나중" not in json.dumps(data, ensure_ascii=False)
    store.save_daily(2, "2026-12-15", [DailyRecord(503, 1, 1, "다른 서버", None)], NOW + timedelta(days=50))
    assert store.keep_only([1]) >= 1 and store.week(2, "2026-12-14", "2026-12-20") == {}
    SQLiteWatchStore(path).remove_guild(1)
    with closing(sqlite3.connect(path)) as connection:
        for table in ("diet_daily", "diet_week_runs", "exercise_settings"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_exercise_lines_are_in_the_catalog() -> None:
    home = guild()
    for text in (exercise_message(home, None, None), exercise_message(home, 10, ROLE)):
        assert unmatched(text) == [], text
