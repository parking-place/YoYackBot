"""`/말하자면` (1.3.4): `!!말하자면` without a visible command — the answer pops up alone."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord
from discord import app_commands


def install_idiom_command(
    tree: app_commands.CommandTree,
    run: Callable[[discord.Interaction], Awaitable[None]],
) -> None:
    # Anyone may use it, like `!!말하자면`; the watched-channel check runs inside `run`.
    @app_commands.guild_only()
    async def idiom(interaction: discord.Interaction) -> None:
        await run(interaction)

    tree.add_command(app_commands.Command(
        name="말하자면", description="최근 대화를 네 글자로 한마디 해 줄게", callback=idiom,
    ))
