"""1.4.0-P1: the 처형 log channel and 처형 roles, with their permission rules (T140-P1-A/B)."""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands
from test_role_config import EVERYONE, MANAGED, OTHER, ROLE, ROLES, guild, interaction

from yoyackbot.channel_config import NOT_ALLOWED, SLASH_PERMISSIONS
from yoyackbot.execution import SQLiteExecutionStore
from yoyackbot.execution_config import (
    ADMIN_ONLY,
    DENIED,
    EXPIRED,
    INVALID_CHANNEL,
    INVALID_ROLE,
    ChannelView,
    RolesView,
    install_execution_settings,
)
from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.settings_backup import backup_settings, restore_settings
from yoyackbot.watch_store import SQLiteWatchStore

MANAGER = OTHER  # a role that exists in the fake server


def setup(tmp_path):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({10}))
    store = SQLiteExecutionStore(path)
    roles = MemoryManagerRoleStore()
    roles.replace(1, frozenset({MANAGER}), expected_version=0)
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    install_execution_settings(tree, store, roles)
    group = tree.get_command("처형설정")
    return path, store, roles, group.get_command("채널관리"), group.get_command("관리역할"), group


def said(item) -> str | None:
    calls = item.response.send_message.await_args_list + item.followup.send.await_args_list
    return calls[-1].args[0] if calls else None


def opened_view(item):
    return item.edit_original_response.await_args.kwargs["view"]


def child(view, label=None, kind=None):
    return next(c for c in view.children
                if (label is None or getattr(c, "label", None) == label) and (kind is None or isinstance(c, kind)))


async def press(view, label, who):
    item = child(view, label)
    if await view.interaction_check(who):
        await item.callback(who)


async def pick(view, kind, values, who):
    select = child(view, kind=kind)
    select._values = values
    if await view.interaction_check(who):
        await select.callback(who)


# T140-P1-A ------------------------------------------------------------------------------

def test_store_round_trip(tmp_path) -> None:
    _path, store, *_ = setup(tmp_path)
    assert store.log_channel(1) is None and store.roles(1) == frozenset()
    store.set_log_channel(1, 10)
    store.set_roles(1, [ROLE, OTHER, ROLE])
    assert store.log_channel(1) == 10 and store.roles(1) == {ROLE, OTHER}
    store.set_roles(1, [OTHER])
    store.set_log_channel(1, None)
    assert store.log_channel(1) is None and store.roles(1) == {OTHER}
    with pytest.raises(ValueError):
        store.set_log_channel(0, 10)
    with pytest.raises(ValueError):
        store.set_roles(1, [0])


def test_commands_are_registered_and_checked_at_run_time(tmp_path) -> None:
    _path, _store, _roles, channel, roles_command, group = setup(tmp_path)
    assert group.guild_only and group.default_permissions == SLASH_PERMISSIONS
    for command in (channel, roles_command):
        assert getattr(command.callback, "__yoyack_gated__", False)


def test_channel_screen_for_admins_and_manager_roles(tmp_path, monkeypatch) -> None:
    _path, store, _roles, channel, _r, _g = setup(tmp_path)
    home = guild()

    async def scenario():
        nobody = interaction(home=home)
        await channel.callback(nobody)
        assert said(nobody) == NOT_ALLOWED
        manager = interaction(home=home, roles=(MANAGER,))
        await channel.callback(manager)
        view = opened_view(manager)
        assert isinstance(view, ChannelView)
        assert manager.edit_original_response.await_args.kwargs["content"].startswith("📜 처형 로그 채널: 없음")
        bad = interaction(home=home, roles=(MANAGER,))
        await pick(view, discord.ui.ChannelSelect, [SimpleNamespace(id=11)], bad)
        assert said(bad) == INVALID_CHANNEL and view.draft is None
        await pick(view, discord.ui.ChannelSelect, [SimpleNamespace(id=10)], interaction(home=home, roles=(MANAGER,)))
        await press(view, "저장", interaction(home=home, roles=(MANAGER,)))
        assert store.log_channel(1) == 10 and view.is_finished()
        admin = interaction(home=home, admin=True)
        await channel.callback(admin)
        again = opened_view(admin)
        await press(again, "해제", interaction(home=home, admin=True))
        await press(again, "저장", interaction(home=home, admin=True))
        assert store.log_channel(1) is None

    asyncio.run(scenario())


def test_roles_screen_is_for_administrators_only(tmp_path) -> None:
    _path, store, _roles, _c, roles_command, _g = setup(tmp_path)
    home = guild()

    async def scenario():
        manager = interaction(home=home, roles=(MANAGER,))
        await roles_command.callback(manager)
        assert said(manager) == ADMIN_ONLY
        manager.edit_original_response.assert_not_awaited()
        admin = interaction(home=home, admin=True)
        await roles_command.callback(admin)
        view = opened_view(admin)
        assert isinstance(view, RolesView) and "없음(관리자만 사용)" in admin.edit_original_response.await_args.kwargs["content"]
        for bad_role in (EVERYONE, MANAGED):
            who = interaction(home=home, admin=True)
            await pick(view, discord.ui.RoleSelect, [ROLES[bad_role]], who)
            assert said(who) == INVALID_ROLE
        await pick(view, discord.ui.RoleSelect, [ROLES[ROLE], ROLES[OTHER]], interaction(home=home, admin=True))
        demoted = interaction(home=home, roles=(MANAGER,))
        await press(view, "저장", demoted)                       # lost admin since opening
        assert said(demoted) == ADMIN_ONLY and store.roles(1) == frozenset()
        stranger = interaction(home=home, admin=True, user_id=8)
        await press(view, "저장", stranger)
        assert said(stranger) == DENIED
        await press(view, "저장", interaction(home=home, admin=True))
        assert store.roles(1) == {ROLE, OTHER} and view.is_finished()
        late = interaction(home=home, admin=True)
        await roles_command.callback(late)
        stale = opened_view(late)
        stale.expires_at = 0
        who = interaction(home=home, admin=True)
        await press(stale, "전체 해제", who)
        assert said(who) == EXPIRED and store.roles(1) == {ROLE, OTHER}

    asyncio.run(scenario())


def test_the_owner_counts_as_an_administrator(tmp_path) -> None:
    _path, _store, _roles, _c, roles_command, _g = setup(tmp_path)
    home = guild()
    home.owner_id = 7

    async def scenario():
        owner = interaction(home=home)
        await roles_command.callback(owner)
        assert isinstance(opened_view(owner), RolesView)

    asyncio.run(scenario())


# T140-P1-B ------------------------------------------------------------------------------

def count(path, table):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_cleanup_paths(tmp_path) -> None:
    path, store, *_ = setup(tmp_path)
    watches = SQLiteWatchStore(path)
    watches.replace(2, frozenset({20}))
    for guild_id, channel in ((1, 10), (2, 20), (3, 30)):
        store.set_log_channel(guild_id, channel)
        store.set_roles(guild_id, [ROLE, OTHER])
    assert store.remove_channel(1, 10) and store.log_channel(1) is None and not store.remove_channel(1, 10)
    assert store.remove_role(2, ROLE) and store.roles(2) == {OTHER}
    watches.remove_guild(2)
    assert store.log_channel(2) is None and store.roles(2) == frozenset()
    assert store.keep_only([1]) == 3  # server 3's channel and two roles
    assert (count(path, "execution_settings"), count(path, "execution_roles")) == (0, 2)


def test_client_handlers_clean_up(tmp_path) -> None:
    from yoyackbot.config import Settings
    from yoyackbot.discord import YoYackClient
    from yoyackbot.message_store import SQLiteMessageStore

    path = tmp_path / "db.sqlite"
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_DB_PATH": str(path)})
    client = YoYackClient(watch_store=SQLiteWatchStore(path), message_store=SQLiteMessageStore(path),
                          settings=settings)
    client.executions.set_log_channel(1, 10)
    client.executions.set_roles(1, [ROLE])

    async def scenario():
        try:
            await client.on_guild_channel_delete(SimpleNamespace(id=10, guild=SimpleNamespace(id=1)))
            await client.on_guild_role_delete(SimpleNamespace(id=ROLE, guild=SimpleNamespace(id=1)))
        finally:
            await client.close()

    asyncio.run(scenario())
    assert client.executions.log_channel(1) is None and client.executions.roles(1) == frozenset()
    assert client.tree.get_command("처형설정") is not None


def test_backup_and_restore(tmp_path) -> None:
    path, store, *_ = setup(tmp_path)
    store.set_log_channel(1, 10)
    store.set_roles(1, [ROLE, OTHER])
    backup = backup_settings(path, tmp_path / "backups")
    data = json.loads(backup.read_text())
    assert [row[:2] for row in data["execution_channel"]] == [[1, 10]]
    assert [row[:2] for row in data["execution_roles"]] == [[1, ROLE], [1, OTHER]]
    restored = tmp_path / "restored.sqlite"
    restore_settings(backup, restored, live_database=path)
    copy = SQLiteExecutionStore(restored)
    assert copy.log_channel(1) == 10 and copy.roles(1) == {ROLE, OTHER}
    for key in ("execution_channel", "execution_roles"):
        del data[key]  # a 1.3.4 backup
    backup.write_text(json.dumps(data))
    older = tmp_path / "older.sqlite"
    restore_settings(backup, older, live_database=path)
    assert SQLiteExecutionStore(older).log_channel(1) is None


def test_logs_keep_no_names(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    _path, _store, _roles, channel, _r, _g = setup(tmp_path)
    home = guild()

    async def scenario():
        admin = interaction(home=home, admin=True)
        await channel.callback(admin)
        view = opened_view(admin)
        await pick(view, discord.ui.ChannelSelect, [SimpleNamespace(id=10)], interaction(home=home, admin=True))
        await press(view, "저장", interaction(home=home, admin=True))

    asyncio.run(scenario())
    assert "execution_channel_saved set=true" in caplog.text and "<#" not in caplog.text
