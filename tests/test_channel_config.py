"""Channel configuration: administrators and bot manager roles, decided by the bot at run time."""

import asyncio
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord import app_commands

from yoyackbot.channel_config import (
    DENIED,
    GUILD_ONLY,
    NOT_ALLOWED,
    SLASH_PERMISSIONS,
    ChannelSettingsView,
    MemoryWatchStore,
    allowed,
    bot_command,
    command_group,
    gated,
    install_channel_commands,
    may_manage,
    selection_summary,
    valid_selection,
)
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

MANAGER_ROLE = 55


def member(*, admin: bool = False, manage: bool = False, roles: tuple[int, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=admin, manage_channels=manage),
        roles=[SimpleNamespace(id=role) for role in roles],
    )


def walk(commands):
    for command in commands:
        if isinstance(command, app_commands.Group):
            yield from walk(command.commands)
        else:
            yield command


def test_every_slash_command_of_the_bot_is_visible_and_gated(tmp_path: Path) -> None:
    async def scenario() -> None:
        path = tmp_path / "db.sqlite"
        client = YoYackClient(
            watch_store=SQLiteWatchStore(path), message_store=SQLiteMessageStore(path),
            settings=Settings.from_environment({
                "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path),
            }),
            clock=lambda: datetime(2026, 10, 1, 12, tzinfo=UTC),
        )
        try:
            top = client.tree.get_commands()
            assert top, "the bot registers slash commands"
            for command in top:
                assert command.guild_only is True, command.name
                assert command.default_permissions == SLASH_PERMISSIONS, command.name
            leaves = list(walk(top))
            assert leaves and all(getattr(c.callback, "__yoyack_gated__", False) for c in leaves)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_helpers_gate_new_commands_too() -> None:
    roles = MemoryManagerRoleStore()
    group = command_group("새그룹", "합성")
    assert group.guild_only and group.default_permissions == SLASH_PERMISSIONS

    @bot_command(roles)
    async def later(interaction: discord.Interaction) -> None:
        return None

    command = app_commands.Command(name="나중", description="합성", callback=later)
    assert command.guild_only and command.default_permissions == SLASH_PERMISSIONS
    assert getattr(command.callback, "__yoyack_gated__", False)


@pytest.mark.parametrize(
    ("who", "expected"),
    [({"admin": True}, True), ({"manage": True}, True), ({"roles": (MANAGER_ROLE,)}, True),
     ({"roles": (99,)}, False), ({}, False)],
)
def test_permission_rule(who: dict, expected: bool) -> None:
    assert may_manage(member(**who), frozenset({MANAGER_ROLE})) is expected
    assert may_manage(SimpleNamespace(), frozenset({MANAGER_ROLE})) is False


def interaction(*, guild: object | None, user_id: int = 7, **who) -> SimpleNamespace:
    response = SimpleNamespace(done=False, send_message=AsyncMock(), edit_message=AsyncMock())
    response.is_done = lambda: response.done

    async def defer(**kwargs) -> None:
        response.done = True

    response.defer = AsyncMock(side_effect=defer)
    return SimpleNamespace(
        guild=guild, guild_id=getattr(guild, "id", None),
        user=SimpleNamespace(id=user_id, **vars(member(**who))),
        response=response,
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
        original_response=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())),
    )


def text_guild(guild_id: int = 1) -> SimpleNamespace:
    text = Mock(spec=discord.TextChannel)
    text.permissions_for.return_value = SimpleNamespace(
        view_channel=True, read_message_history=True, send_messages=True
    )
    text.mention = "#합성"
    return SimpleNamespace(id=guild_id, me=object(), get_channel=lambda cid: text if cid == 10 else None)


def configure_command(store, roles):
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    install_channel_commands(tree, store, roles)
    return tree.get_command("채널").get_command("설정")  # type: ignore[union-attr]


@pytest.mark.parametrize("who", [{"admin": True}, {"manage": True}, {"roles": (MANAGER_ROLE,)}])
def test_admins_and_manager_roles_can_open_and_save(who: dict, caplog) -> None:
    caplog.set_level(logging.INFO)
    guild = text_guild()

    async def scenario() -> None:
        store, roles = MemoryWatchStore(), MemoryManagerRoleStore()
        roles.replace(1, frozenset({MANAGER_ROLE}))
        opened = interaction(guild=guild, **who)
        await configure_command(store, roles).callback(opened)
        view = opened.edit_original_response.await_args.kwargs["view"]
        assert isinstance(view, ChannelSettingsView) and view.owner_id == 7
        assert opened.response.defer.await_args.kwargs["ephemeral"] is True
        click = interaction(guild=guild, **who)
        assert await view.interaction_check(click)
        view.draft.add(10)
        save = next(item for item in view.children if getattr(item, "label", "") == "저장")
        await save.callback(click)
        assert store.get(1) == frozenset({10})

    asyncio.run(scenario())
    saved = [r.getMessage() for r in caplog.records if r.getMessage().startswith("watched_channels_saved")]
    assert len(saved) == 1
    assert re.fullmatch(r"watched_channels_saved at=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ count=1", saved[0])


@pytest.mark.parametrize("who", [{}, {"roles": (99,)}])
def test_everyone_else_is_refused_privately(who: dict) -> None:
    async def scenario() -> None:
        roles = MemoryManagerRoleStore()
        roles.replace(1, frozenset({MANAGER_ROLE}))
        attempt = interaction(guild=text_guild(), **who)
        await configure_command(MemoryWatchStore(), roles).callback(attempt)
        assert attempt.followup.send.await_args.args == (NOT_ALLOWED,)
        assert attempt.followup.send.await_args.kwargs["ephemeral"] is True

    asyncio.run(scenario())


def test_direct_messages_are_refused() -> None:
    async def scenario() -> None:
        dm = interaction(guild=None, admin=True)
        await configure_command(MemoryWatchStore(), MemoryManagerRoleStore()).callback(dm)
        assert dm.response.send_message.await_args.args == (GUILD_ONLY,)

    asyncio.run(scenario())


def test_unreadable_role_table_still_lets_administrators_in() -> None:
    class Broken(MemoryManagerRoleStore):
        def get(self, guild_id: int) -> frozenset[int]:
            raise RuntimeError("synthetic")

    async def scenario() -> None:
        called = []

        @gated(Broken())
        async def run(interaction) -> None:
            called.append(interaction.user.id)

        await run(interaction(guild=text_guild(), user_id=1, admin=True))
        member_only = interaction(guild=text_guild(), user_id=2, roles=(MANAGER_ROLE,))
        await run(member_only)
        assert called == [1] and member_only.followup.send.await_args.args == (NOT_ALLOWED,)

    asyncio.run(scenario())


def test_store_replaces_only_one_guild_and_can_clear() -> None:
    store = MemoryWatchStore()
    store.replace(1, frozenset({10, 11}))
    store.replace(2, frozenset({20}))
    store.replace(1, frozenset())
    assert store.get(1) == frozenset()
    assert store.get(2) == frozenset({20})


def test_channel_must_be_visible_text_channel() -> None:
    text = Mock(spec=discord.TextChannel)
    text.permissions_for.return_value = SimpleNamespace(
        view_channel=True, read_message_history=True, send_messages=True
    )
    hidden = Mock(spec=discord.TextChannel)
    hidden.permissions_for.return_value = SimpleNamespace(
        view_channel=False, read_message_history=True, send_messages=True
    )
    guild = SimpleNamespace(me=object(), get_channel=lambda cid: {10: text, 11: hidden}.get(cid))
    assert valid_selection(guild, {10})
    assert not valid_selection(guild, {11})
    assert not valid_selection(guild, {12})
    assert valid_selection(guild, set())


def test_admin_sees_selected_channels_in_ephemeral_summary() -> None:
    channels = {10: SimpleNamespace(mention="#first"), 11: SimpleNamespace(mention="#second")}
    guild = SimpleNamespace(get_channel=channels.get)
    assert selection_summary(guild, {10, 11}) == "📡 현재 주시 채널 2개: #first, #second"
    assert selection_summary(guild, set()) == "📡 현재 주시 채널 0개: 없음"


def test_view_stays_with_its_opener_and_rechecks_the_role_on_every_click() -> None:
    async def scenario() -> None:
        roles = MemoryManagerRoleStore()
        roles.replace(1, frozenset({MANAGER_ROLE}))
        view = ChannelSettingsView(
            MemoryWatchStore(), guild_id=1, owner_id=2, roles=roles, snapshot=(0, frozenset()),
        )
        home, other = text_guild(1), text_guild(2)
        for guild, user_id, who, permitted, message in [
            (home, 2, {"roles": (MANAGER_ROLE,)}, True, None),
            (home, 2, {"admin": True}, True, None),
            (home, 3, {"admin": True}, False, DENIED),
            (other, 2, {"admin": True}, False, DENIED),
            (home, 2, {}, False, NOT_ALLOWED),
        ]:
            click = interaction(guild=guild, user_id=user_id, **who)
            assert await view.interaction_check(click) is permitted
            if message:
                sent = click.followup.send if click.response.is_done() else click.response.send_message
                assert sent.await_args.args[0] == message
        roles.replace(1, frozenset())
        lost = interaction(guild=home, user_id=2, roles=(MANAGER_ROLE,))
        assert not await view.interaction_check(lost)

    asyncio.run(scenario())


def test_authorization_fetches_current_member_when_cache_is_disabled() -> None:
    async def scenario() -> None:
        roles = MemoryManagerRoleStore()
        roles.replace(1, frozenset({MANAGER_ROLE}))
        home = text_guild()
        home.get_member = lambda _user_id: None
        home.fetch_member = AsyncMock(return_value=member(roles=(MANAGER_ROLE,)))
        request = interaction(guild=home, roles=(MANAGER_ROLE,))
        assert await allowed(request, roles)
        home.fetch_member.assert_awaited_once_with(7)
        home.fetch_member.return_value = member()
        assert not await allowed(request, roles)
        assert request.followup.send.await_args.args == (NOT_ALLOWED,)

    asyncio.run(scenario())


def test_save_failure_and_stale_or_expired_views_do_not_report_success() -> None:
    class Broken(MemoryWatchStore):
        def replace(self, *args, **kwargs) -> int:
            raise RuntimeError("synthetic write failure")

    async def scenario() -> None:
        roles = MemoryManagerRoleStore()
        for reason in ("failed", "stale", "expired"):
            store = Broken() if reason == "failed" else MemoryWatchStore()
            view = ChannelSettingsView(store, 1, 7, roles, snapshot=store.snapshot(1))
            view.draft.add(10)
            if reason == "stale":
                store.replace(1, frozenset({99}))
            if reason == "expired":
                await view.on_timeout()
            request = interaction(guild=text_guild(), admin=True)
            save = next(child for child in view.children if getattr(child, "label", None) == "저장")
            await save.callback(request)
            request.edit_original_response.assert_not_awaited()
            assert store.get(1) == (frozenset({99}) if reason == "stale" else frozenset())
            response = request.followup.send if request.response.is_done() else request.response.send_message
            assert any(word in response.await_args.args[0] for word in (
                "저장하지 못했소", "다른 사람이", "설정 시간이",
            ))

    asyncio.run(scenario())
