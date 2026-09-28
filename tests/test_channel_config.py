"""Channel configuration authorization and guild isolation contracts."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from yoyackbot.channel_config import (
    ChannelSettingsView,
    MemoryWatchStore,
    can_manage,
    selection_summary,
    valid_selection,
)


def member(*, admin: bool = False, manage: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        guild_permissions=SimpleNamespace(administrator=admin, manage_channels=manage)
    )


def test_permission_policy() -> None:
    assert can_manage(member(admin=True))
    assert can_manage(member(manage=True))
    assert not can_manage(member())
    assert not can_manage(SimpleNamespace())


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


def test_callback_gate_rechecks_owner_guild_and_current_permission() -> None:
    async def scenario() -> None:
        view = ChannelSettingsView(MemoryWatchStore(), guild_id=1, owner_id=2)
        for guild_id, user_id, allowed in [(1, 2, True), (1, 3, False), (2, 2, False)]:
            interaction = SimpleNamespace(
                guild_id=guild_id,
                user=SimpleNamespace(id=user_id, guild_permissions=member(manage=allowed).guild_permissions),
                response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
            )
            assert await view.interaction_check(interaction) is allowed
            if not allowed:
                interaction.response.send_message.assert_awaited_once()
        revoked = SimpleNamespace(
            guild_id=1,
            user=SimpleNamespace(id=2, guild_permissions=member().guild_permissions),
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        assert not await view.interaction_check(revoked)

    asyncio.run(scenario())
