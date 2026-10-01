"""Channel configuration: Discord command permissions decide, the view stays with its opener."""

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

from yoyackbot import channel_config
from yoyackbot.channel_config import (
    DENIED,
    GUILD_ONLY,
    SLASH_PERMISSIONS,
    ChannelSettingsView,
    MemoryWatchStore,
    install_channel_commands,
    member_command,
    member_group,
    selection_summary,
    valid_selection,
)
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore


def member(*, admin: bool = False, manage: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=admin, manage_channels=manage)
    )


def assert_member_open(command: app_commands.Command | app_commands.Group) -> None:
    assert command.guild_only is True, command.name
    assert command.default_permissions == SLASH_PERMISSIONS, command.name
    payload = command.to_dict(app_commands.CommandTree(discord.Client(intents=discord.Intents.none())))
    assert int(payload["default_member_permissions"]) == 1 << 31, command.name


def test_every_slash_command_of_the_bot_is_open_to_application_command_users(tmp_path: Path) -> None:
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
            commands = client.tree.get_commands()
            assert commands, "the bot registers slash commands"
            for command in commands:
                assert_member_open(command)
        finally:
            await client.close()

    asyncio.run(scenario())
    assert SLASH_PERMISSIONS.value == 1 << 31 and SLASH_PERMISSIONS.use_application_commands


def test_helpers_apply_the_same_rule_to_new_commands() -> None:
    assert_member_open(member_group("새그룹", "합성"))

    @member_command
    async def later(interaction: discord.Interaction) -> None:
        return None

    assert_member_open(app_commands.Command(name="나중", description="합성", callback=later))
    assert not hasattr(channel_config, "can_manage")


def interaction(*, guild: object | None, user_id: int = 7, guild_id: int = 1, **perms) -> SimpleNamespace:
    return SimpleNamespace(
        guild=guild, guild_id=guild_id if guild is not None else None,
        user=SimpleNamespace(id=user_id, guild_permissions=member(**perms).guild_permissions),
        response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock(),
                                 edit_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        original_response=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock())),
    )


@pytest.mark.parametrize("perms", [{"admin": True}, {"manage": True}, {}])
def test_anyone_discord_lets_through_can_open_and_save(perms: dict, caplog) -> None:
    caplog.set_level(logging.INFO)
    text = Mock(spec=discord.TextChannel)
    text.permissions_for.return_value = SimpleNamespace(
        view_channel=True, read_message_history=True, send_messages=True
    )
    text.mention = "#합성"
    guild = SimpleNamespace(id=1, me=object(), get_channel=lambda cid: text if cid == 10 else None)

    async def scenario() -> None:
        store = MemoryWatchStore()
        tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
        install_channel_commands(tree, store)
        configure = tree.get_command("채널").get_command("설정")  # type: ignore[union-attr]
        opened = interaction(guild=guild, **perms)
        await configure.callback(opened)
        view = opened.response.send_message.await_args.kwargs["view"]
        assert isinstance(view, ChannelSettingsView) and view.owner_id == 7
        assert opened.response.send_message.await_args.kwargs["ephemeral"] is True
        click = interaction(guild=guild, **perms)
        assert await view.interaction_check(click)
        view.draft.add(10)
        save = next(item for item in view.children if getattr(item, "label", "") == "저장")
        await save.callback(click)
        assert store.get(1) == frozenset({10})

    asyncio.run(scenario())
    saved = [r.getMessage() for r in caplog.records if r.getMessage().startswith("watched_channels_saved")]
    assert len(saved) == 1
    assert re.fullmatch(r"watched_channels_saved at=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ count=1", saved[0])


def test_direct_messages_are_refused() -> None:
    async def scenario() -> None:
        tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
        install_channel_commands(tree, MemoryWatchStore())
        configure = tree.get_command("채널").get_command("설정")  # type: ignore[union-attr]
        dm = interaction(guild=None, admin=True)
        await configure.callback(dm)
        assert dm.response.send_message.await_args.args == (GUILD_ONLY,)

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
    assert selection_summary(guild, {10, 11}) == "현재 주시 채널 2개: #first, #second"
    assert selection_summary(guild, set()) == "현재 주시 채널 0개: 없음"


def test_callback_gate_keeps_the_view_with_its_opener_in_its_guild() -> None:
    async def scenario() -> None:
        view = ChannelSettingsView(MemoryWatchStore(), guild_id=1, owner_id=2)
        for guild_id, user_id, perms, allowed in [
            (1, 2, {}, True), (1, 2, {"admin": True}, True),
            (1, 3, {"admin": True}, False), (2, 2, {}, False),
        ]:
            click = interaction(guild=object(), guild_id=guild_id, user_id=user_id, **perms)
            assert await view.interaction_check(click) is allowed
            if not allowed:
                assert click.response.send_message.await_args.args[0] == DENIED

    asyncio.run(scenario())
