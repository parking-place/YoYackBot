"""P1-C: defer before SQLite I/O and keep callbacks responsive under a real writer lock."""

import asyncio
import sqlite3
import threading
import time
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord import app_commands

from yoyackbot.channel_config import NOT_ALLOWED, ChannelSettingsView, install_channel_commands
from yoyackbot.manager_roles import SQLiteManagerRoleStore
from yoyackbot.role_config import RoleSettingsView, install_role_commands
from yoyackbot.watch_store import SQLiteWatchStore


def interaction() -> SimpleNamespace:
    response = SimpleNamespace(done=False, send_message=AsyncMock(), edit_message=AsyncMock())
    response.is_done = lambda: response.done

    async def defer(**kwargs) -> None:
        response.done = True
        response.deferred_at = time.monotonic()

    response.defer = AsyncMock(side_effect=defer)
    channel = Mock(spec=discord.TextChannel)
    channel.mention = "#synthetic"
    channel.permissions_for.return_value = SimpleNamespace(
        view_channel=True, read_message_history=True, send_messages=True,
    )
    role = SimpleNamespace(id=55, managed=False, is_default=lambda: False, mention="synthetic")
    guild = SimpleNamespace(
        id=1, me=object(), get_channel=lambda cid: channel if cid == 10 else None,
        get_role=lambda rid: role if rid == 55 else None,
    )
    return SimpleNamespace(
        guild=guild, guild_id=1,
        user=SimpleNamespace(id=7, roles=[], guild_permissions=SimpleNamespace(
            administrator=True, manage_channels=False,
        )),
        response=response, followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(), original_response=AsyncMock(),
    )


class CheckedStore:
    """Fail at the I/O boundary if a callback blocks the loop or misses acknowledgement."""

    def __init__(self, store, request, loop_thread: int) -> None:
        self.store, self.request, self.loop_thread = store, request, loop_thread
        self.calls = []

    def __getattr__(self, name):
        original = getattr(self.store, name)

        def checked(*args, **kwargs):
            assert self.request.response.is_done(), "DB access preceded defer"
            assert threading.get_ident() != self.loop_thread, "DB access blocked the event loop"
            self.calls.append(name)
            return original(*args, **kwargs)

        return checked


@pytest.mark.parametrize("kind", ["channel", "role"])
def test_open_defers_before_auth_and_snapshot_io(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "settings.sqlite"
    watches, roles = SQLiteWatchStore(path), SQLiteManagerRoleStore(path)

    async def scenario() -> None:
        request = interaction()
        checked_roles = CheckedStore(roles, request, threading.get_ident())
        checked_watches = CheckedStore(watches, request, threading.get_ident())
        tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
        if kind == "channel":
            install_channel_commands(tree, checked_watches, checked_roles)
            group = tree.get_command("채널")
        else:
            install_role_commands(tree, checked_roles)
            group = tree.get_command("관리권한")
        await group.get_command("설정").callback(request)
        request.response.defer.assert_awaited_once_with(ephemeral=True)
        assert "get" in checked_roles.calls
        assert "snapshot" in (checked_watches if kind == "channel" else checked_roles).calls
        assert "view" in request.edit_original_response.await_args.kwargs

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["channel", "role"])
def test_save_defers_and_ticks_while_sqlite_writer_is_locked(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "settings.sqlite"
    watches, roles = SQLiteWatchStore(path), SQLiteManagerRoleStore(path)
    watch_snapshot, role_snapshot = watches.snapshot(1), roles.snapshot(1)
    locked = threading.Event()

    def hold_writer() -> None:
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            locked.set()
            time.sleep(4)

    async def scenario() -> None:
        request = interaction()
        checked_roles = CheckedStore(roles, request, threading.get_ident())
        if kind == "channel":
            target = CheckedStore(watches, request, threading.get_ident())
            view = ChannelSettingsView(
                target, 1, 7, checked_roles, snapshot=watch_snapshot,
            )
            view.draft.add(10)
        else:
            target = checked_roles
            view = RoleSettingsView(target, 1, 7, snapshot=role_snapshot)
            view.draft.add(55)
        worker = asyncio.create_task(asyncio.to_thread(hold_writer))
        assert await asyncio.to_thread(locked.wait, 2)
        ticks = []

        async def heartbeat() -> None:
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.05)

        pulse = asyncio.create_task(heartbeat())
        started = time.monotonic()
        save = next(child for child in view.children if getattr(child, "label", None) == "저장")
        try:
            await save.callback(request)
            ticks.append(time.monotonic())
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
            await worker
        assert time.monotonic() - started >= 3.5, "the callback did not exercise the writer wait"
        assert request.response.deferred_at - started < 1
        assert len(ticks) >= 50
        assert max(b - a for a, b in pairwise(ticks)) < 0.25
        assert "replace" in target.calls
        assert "저장했소" in request.edit_original_response.await_args.kwargs["content"]
        assert view.is_finished()

    asyncio.run(scenario())
    assert (watches if kind == "channel" else roles).get(1) == frozenset(
        {10} if kind == "channel" else {55}
    )


@pytest.mark.parametrize("kind", ["channel", "role"])
def test_response_failure_after_commit_keeps_saved_state(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "settings.sqlite"
    watches, roles = SQLiteWatchStore(path), SQLiteManagerRoleStore(path)
    snapshot = (watches if kind == "channel" else roles).snapshot(1)

    async def scenario() -> None:
        request = interaction()
        request.edit_original_response.side_effect = RuntimeError("synthetic response failure")
        if kind == "channel":
            view = ChannelSettingsView(watches, 1, 7, roles, snapshot=snapshot)
            view.draft.add(10)
        else:
            view = RoleSettingsView(roles, 1, 7, snapshot=snapshot)
            view.draft.add(55)
        save = next(child for child in view.children if getattr(child, "label", None) == "저장")
        with pytest.raises(RuntimeError, match="synthetic response failure"):
            await save.callback(request)
        assert view.is_finished()
        request.followup.send.assert_not_awaited()

    asyncio.run(scenario())
    assert (watches if kind == "channel" else roles).get(1) == frozenset(
        {10} if kind == "channel" else {55}
    )


@pytest.mark.parametrize("kind", ["channel", "role"])
@pytest.mark.parametrize("revoked", ["settings", "discord"])
def test_permission_revoked_during_writer_wait_cannot_commit(
    tmp_path: Path, kind: str, revoked: str,
) -> None:
    path = tmp_path / "settings.sqlite"
    watches, roles = SQLiteWatchStore(path), SQLiteManagerRoleStore(path)
    roles.replace(1, frozenset({55}))
    snapshot = (watches if kind == "channel" else roles).snapshot(1)
    locked, checked, changed = threading.Event(), threading.Event(), threading.Event()

    def hold_and_revoke() -> None:
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            locked.set()
            assert checked.wait(2), "the UI never checked initial permission"
            time.sleep(0.15)
            if revoked == "settings":
                connection.execute("DELETE FROM manager_roles WHERE guild_id=1")
                connection.execute("UPDATE manager_role_meta SET version=version+1 WHERE guild_id=1")
            changed.set()

    async def scenario() -> None:
        request = interaction()
        request.user.guild_permissions.administrator = False
        request.user.roles = [SimpleNamespace(id=55)]

        async def current_member(_user_id: int):
            present = not (revoked == "discord" and changed.is_set())
            checked.set()
            return SimpleNamespace(
                guild_permissions=SimpleNamespace(administrator=False, manage_channels=False),
                roles=[SimpleNamespace(id=55)] if present else [],
            )

        request.guild.fetch_member = AsyncMock(side_effect=current_member)
        request.guild.get_member = lambda _user_id: None
        if kind == "channel":
            view = ChannelSettingsView(watches, 1, 7, roles, snapshot=snapshot)
            view.draft.add(10)
        else:
            view = RoleSettingsView(roles, 1, 7, snapshot=snapshot)
            view.draft.clear()
        worker = asyncio.create_task(asyncio.to_thread(hold_and_revoke))
        assert await asyncio.to_thread(locked.wait, 2)
        save = next(child for child in view.children if getattr(child, "label", None) == "저장")
        try:
            await save.callback(request)
        finally:
            await worker
        assert changed.is_set()
        assert request.guild.fetch_member.await_count == 2
        assert request.followup.send.await_args.args == (NOT_ALLOWED,)
        request.edit_original_response.assert_not_awaited()

    asyncio.run(scenario())
    assert watches.get(1) == frozenset()
    assert roles.get(1) == (frozenset() if revoked == "settings" else frozenset({55}))


@pytest.mark.parametrize("kind", ["channel", "role"])
def test_new_draft_selection_deleted_during_writer_wait_cannot_commit(
    tmp_path: Path, kind: str,
) -> None:
    path = tmp_path / "settings.sqlite"
    watches, roles = SQLiteWatchStore(path), SQLiteManagerRoleStore(path)
    target = watches if kind == "channel" else roles
    snapshot = target.snapshot(1)
    locked, checked, deleted = threading.Event(), threading.Event(), threading.Event()

    def hold_writer() -> None:
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            locked.set()
            assert checked.wait(2), "the UI never checked initial permission"
            time.sleep(0.15)
            deleted.set()

    async def scenario() -> None:
        request = interaction()
        original_lookup = request.guild.get_channel if kind == "channel" else request.guild.get_role

        def lookup(identifier):
            return None if deleted.is_set() else original_lookup(identifier)

        if kind == "channel":
            request.guild.get_channel = lookup
            view = ChannelSettingsView(watches, 1, 7, roles, snapshot=snapshot)
            view.draft.add(10)
        else:
            request.guild.get_role = lookup
            view = RoleSettingsView(roles, 1, 7, snapshot=snapshot)
            view.draft.add(55)

        async def current_member(_user_id: int):
            checked.set()
            return request.user

        request.guild.fetch_member = AsyncMock(side_effect=current_member)
        worker = asyncio.create_task(asyncio.to_thread(hold_writer))
        assert await asyncio.to_thread(locked.wait, 2)
        save = next(child for child in view.children if getattr(child, "label", None) == "저장")
        try:
            await save.callback(request)
        finally:
            await worker
        assert deleted.is_set()
        assert request.guild.fetch_member.await_count == 2
        assert "다른 사람이 설정을 바꾸었소" in request.followup.send.await_args.args[0]
        request.edit_original_response.assert_not_awaited()
        assert not view.is_finished()
        # Deleted roles can be pruned on the next attempt without clearing still-valid choices.
        if kind == "role":
            retry = interaction()
            retry.guild.get_role = lookup
            await save.callback(retry)
            assert "사라진 역할" in retry.edit_original_response.await_args.kwargs["content"]

    asyncio.run(scenario())
    assert target.snapshot(1) == snapshot
