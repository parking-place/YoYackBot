"""1.3.1-P2: `/도움말` shows the help only to the caller; text help points there (T131-P2-A/B)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.help_command import install_help_command
from yoyackbot.parser import HELP_MOVED_NOTICE, HELP_TEXT, USAGE_NOTICE, help_text


def tree() -> app_commands.CommandTree:
    return app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))


def interaction(**member) -> SimpleNamespace:
    """A plain member: no administrator, no channel management, no manager role."""
    guild = SimpleNamespace(id=1, get_role=lambda _id: None, fetch_member=AsyncMock())
    return SimpleNamespace(
        guild=guild, guild_id=1,
        user=SimpleNamespace(id=7, guild_permissions=discord.Permissions.none(), roles=(), **member),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: False),
        followup=SimpleNamespace(send=AsyncMock()),
    )


# T131-P2-A ------------------------------------------------------------------------------

@pytest.mark.parametrize("days", ["1", "7", "30"])
def test_any_member_gets_the_help_privately(days, caplog) -> None:
    caplog.set_level(logging.INFO)
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "synthetic", "YOYACK_MAX_DAYS": days})
    commands = tree()
    install_help_command(commands, settings)
    command = commands.get_command("도움말")
    assert command.guild_only and command.default_permissions is None
    asked = interaction()
    asyncio.run(command.callback(asked))
    asked.response.send_message.assert_awaited_once()
    args, kwargs = asked.response.send_message.await_args
    assert args == (help_text(settings),) and kwargs["ephemeral"] is True
    assert not kwargs["allowed_mentions"].everyone and not kwargs["allowed_mentions"].roles
    asked.guild.fetch_member.assert_not_awaited()  # no manager-role check
    asked.response.defer.assert_not_awaited()
    assert "help_request surface=slash" in caplog.text and "요약 사용법" not in caplog.text


def test_the_help_body_is_unchanged_and_hides_the_speed_setting() -> None:
    assert HELP_TEXT.startswith("📜 **요약 사용법**\n") and len(HELP_TEXT) < 2000
    for text in (HELP_TEXT, help_text()):
        assert "속도" not in text and "빠른" not in text and "/도움말" not in text


def test_the_client_registers_the_command() -> None:
    async def scenario():
        client = YoYackClient(watch_store=MemoryWatchStore())
        try:
            assert client.tree.get_command("도움말") is not None
        finally:
            await client.close()

    asyncio.run(scenario())


# T131-P2-B ------------------------------------------------------------------------------

@pytest.mark.parametrize("content", [
    "!!요약좀 도움", "!!요약좀 도움말", "신창섭아 !!요약좀 3시간 도움", "!!요약좀 2시간 !!요약좀 도움",
    "!!요약좀 사용량 도움",
])
@pytest.mark.parametrize("watched", [True, False])
def test_text_help_posts_one_pointer_line(content, watched, caplog) -> None:
    caplog.set_level(logging.INFO)

    async def scenario():
        store = MemoryWatchStore()
        if watched:
            store.replace(1, frozenset({99}))
        sent = AsyncMock()
        client = YoYackClient(watch_store=store)
        message = SimpleNamespace(
            guild=SimpleNamespace(id=1), channel=SimpleNamespace(type=discord.ChannelType.text, id=99, send=sent),
            author=SimpleNamespace(bot=False), webhook_id=None, type=discord.MessageType.default,
            content=content,
        )
        try:
            await client.on_message(message)
        finally:
            await client.close()
        return sent

    sent = asyncio.run(scenario())
    sent.assert_awaited_once()
    assert sent.await_args.args == (HELP_MOVED_NOTICE,)
    assert "help_request surface=text" in caplog.text and content not in caplog.text


def test_notices_point_at_the_slash_command() -> None:
    assert "`/도움말`" in USAGE_NOTICE and "!!요약좀 도움" not in USAGE_NOTICE
    assert HELP_MOVED_NOTICE.startswith("📜") and "`/도움말`" in HELP_MOVED_NOTICE
