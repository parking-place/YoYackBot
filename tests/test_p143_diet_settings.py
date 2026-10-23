"""1.4.3-P1: `/돼지채널 설정`·`/돼지역할 설정` and the member intent (T143-P1-A/B)."""

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
from test_role_config import EVERYONE, MANAGED, OTHER, ROLE, guild, interaction

from yoyackbot.channel_config import NOT_ALLOWED, SLASH_PERMISSIONS
from yoyackbot.diet import SQLiteDietStore
from yoyackbot.diet_config import (
    MENTION_WARNING,
    SCHEDULE_OFF,
    SCHEDULE_ON,
    DietView,
    install_diet_settings,
    status_message,
)
from yoyackbot.discord import required_intents
from yoyackbot.execution_config import DENIED, EXPIRED, INVALID_ROLE
from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.notices import unmatched
from yoyackbot.settings_backup import backup_settings, restore_settings
from yoyackbot.watch_store import SQLiteWatchStore

MANAGER = OTHER


def setup(tmp_path):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({10}))
    store = SQLiteDietStore(path)
    roles = MemoryManagerRoleStore()
    roles.replace(1, frozenset({MANAGER}), expected_version=0)
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    install_diet_settings(tree, store, roles)
    channel_group, role_group = tree.get_command("돼지채널"), tree.get_command("돼지역할")
    return path, store, channel_group, role_group


# T143-P1-A ------------------------------------------------------------------------------

def test_store_round_trip(tmp_path) -> None:
    _path, store, *_ = setup(tmp_path)
    assert store.settings(1) == (None, None) and store.configured() == []
    store.set_channel(1, 10)
    assert store.settings(1) == (10, None) and store.configured() == []
    store.set_role(1, ROLE)
    assert store.configured() == [(1, 10, ROLE)]
    store.set_channel(1, None)
    assert store.settings(1) == (None, ROLE)
    store.set_role(1, None)
    with sqlite3.connect(store.path) as connection:            # nothing left: the row goes
        assert connection.execute("SELECT COUNT(*) FROM diet_settings").fetchone()[0] == 0
    with pytest.raises(ValueError):
        store.set_channel(0, 10)


def test_commands_are_gated_server_only_groups(tmp_path) -> None:
    _path, _store, channel_group, role_group = setup(tmp_path)
    for group in (channel_group, role_group):
        assert group.guild_only and group.default_permissions == SLASH_PERMISSIONS
        command = group.get_command("설정")
        assert getattr(command.callback, "__yoyack_gated__", False)


def test_channel_and_role_screens(tmp_path) -> None:
    _path, store, channel_group, role_group = setup(tmp_path)
    home = guild()

    async def scenario():
        nobody = interaction(home=home)
        await channel_group.get_command("설정").callback(nobody)
        assert said(nobody) == NOT_ALLOWED
        manager = interaction(home=home, roles=(MANAGER,))
        await channel_group.get_command("설정").callback(manager)
        view = opened_view(manager)
        assert isinstance(view, DietView)
        opened = manager.edit_original_response.await_args.kwargs["content"]
        assert opened.startswith("🐷 식단 채널: 없음(재촉하지 않음)\n🐷 식단 역할: 없음") and SCHEDULE_OFF in opened
        await pick(view, discord.ui.ChannelSelect, [SimpleNamespace(id=10)], manager)
        await press(view, "저장", manager)
        assert store.settings(1) == (10, None)

        admin = interaction(home=home, admin=True)
        await role_group.get_command("설정").callback(admin)
        roles_view = opened_view(admin)
        await pick(roles_view, discord.ui.RoleSelect, [SimpleNamespace(id=MANAGED)], admin)
        assert said(admin) == INVALID_ROLE
        await pick(roles_view, discord.ui.RoleSelect, [SimpleNamespace(id=ROLE)], admin)
        await press(roles_view, "저장", admin)
        saved = admin.edit_original_response.await_args.kwargs["content"]
        assert store.configured() == [(1, 10, ROLE)] and SCHEDULE_ON in saved
        assert MENTION_WARNING in saved                      # fake role is not mentionable

        again = interaction(home=home, admin=True)
        await role_group.get_command("설정").callback(again)
        clearing = opened_view(again)
        await press(clearing, "해제", again)
        await press(clearing, "저장", again)
        assert store.settings(1) == (10, None)

    asyncio.run(scenario())


def test_opener_only_and_time_limit(tmp_path) -> None:
    _path, store, *_ = setup(tmp_path)
    home = guild()
    roles = MemoryManagerRoleStore()

    async def scenario():
        view = DietView(store, roles, 1, 7, (None, None), kind="channel")
        stranger = interaction(home=home, user_id=8, admin=True)
        assert not await view.interaction_check(stranger) and said(stranger) == DENIED
        view.expires_at = 0
        late = interaction(home=home, admin=True)
        assert not await view.interaction_check(late) and said(late) == EXPIRED

    asyncio.run(scenario())


def test_mention_rule() -> None:
    home = guild()
    assert MENTION_WARNING in status_message(home, 10, ROLE)
    home.get_role = lambda rid: SimpleNamespace(id=rid, mention=f"<@&{rid}>", mentionable=True)
    assert MENTION_WARNING not in status_message(home, 10, ROLE)
    home.get_role = lambda rid: SimpleNamespace(id=rid, mention=f"<@&{rid}>", mentionable=False)
    home.me = SimpleNamespace(guild_permissions=SimpleNamespace(mention_everyone=True))
    home.get_channel = lambda cid: SimpleNamespace(
        mention=f"<#{cid}>", permissions_for=lambda me: SimpleNamespace(mention_everyone=True))
    assert MENTION_WARNING not in status_message(home, 10, ROLE)


# T143-P1-B ------------------------------------------------------------------------------

def test_member_intent_is_requested() -> None:
    intents = required_intents()
    assert intents.members and intents.moderation and intents.message_content


def test_cleanup_backup_and_runs(tmp_path) -> None:
    path, store, *_ = setup(tmp_path)
    store.set_channel(1, 10)
    store.set_role(1, ROLE)
    store.set_channel(2, 20)
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    assert store.claim(1, "2026-10-18", "call", "running", now) is True
    assert store.claim(1, "2026-10-18", "call", "running", now) is False      # once a day
    store.finish(1, "2026-10-18", "call", "posted")
    assert store.done(1, "2026-10-18") == {"call": "posted"}
    store.claim(1, "2026-09-01", "judge", "posted", now - timedelta(days=47))
    store.claim(1, "2026-10-19", "nag", "running", now)                      # prunes 40+ days
    assert "judge" not in store.done(1, "2026-09-01")
    data = json.loads(backup_settings(path, tmp_path / "backups").read_text())
    assert sorted(data["diet"]) == [[1, 10, ROLE, data["diet"][0][3]], [2, 20, None, data["diet"][1][3]]]
    restored = tmp_path / "restored.sqlite"
    restore_settings(backup_settings(path, tmp_path / "backups"), restored, live_database=path)
    assert SQLiteDietStore(restored).configured() == [(1, 10, ROLE)]
    assert store.remove_role(1, ROLE) and store.settings(1) == (10, None)
    assert store.remove_channel(2, 20) and store.settings(2) == (None, None)
    assert not store.remove_channel(2, 20)
    store.set_role(3, ROLE)
    assert store.keep_only([1]) >= 1 and store.settings(3) == (None, None)
    SQLiteWatchStore(path).remove_guild(1)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM diet_settings").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM diet_runs").fetchone()[0] == 0


def test_settings_lines_are_in_the_catalog() -> None:
    home = guild()
    for text in (status_message(home, None, None), status_message(home, 10, ROLE)):
        assert unmatched(text) == [], text
    assert EVERYONE  # the fake server's @everyone exists for role checks
