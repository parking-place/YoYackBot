"""`/도움말` (1.3.1) and `/처형도움` (1.4.1b): help shown only to whoever asked, open to every
member."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from yoyackbot.config import Settings
from yoyackbot.notices import localize
from yoyackbot.parser import EXECUTION_HELP, help_text

LOGGER = logging.getLogger(__name__)


def install_help_command(tree: app_commands.CommandTree, settings: Settings | None) -> None:
    # No manager-role gate and no default permission: every member of the server may ask.
    @app_commands.guild_only()
    async def show_help(interaction: discord.Interaction) -> None:
        LOGGER.info("help_request surface=slash")
        await interaction.response.send_message(
            localize(interaction.guild_id, help_text(settings)), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    tree.add_command(app_commands.Command(
        name="도움말", description="요약봇 사용법을 나에게만 보여 주오", callback=show_help,
    ))


def install_execution_help(tree: app_commands.CommandTree) -> None:
    # Like `/도움말`: every member may ask, and only the caller sees it.
    @app_commands.guild_only()
    async def show_execution_help(interaction: discord.Interaction) -> None:
        LOGGER.info("help_request surface=execution")
        await interaction.response.send_message(
            localize(interaction.guild_id, EXECUTION_HELP), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    tree.add_command(app_commands.Command(
        name="처형도움", description="처형·사면 명령 사용법을 나에게만 보여 주오",
        callback=show_execution_help,
    ))
