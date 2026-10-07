"""`/속도 설정`: turn this server's fast service tier on or off (1.3.1, not in the help)."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

import discord
from discord import app_commands

from yoyackbot.channel_config import allowed, command_group, gated, reject
from yoyackbot.manager_roles import ManagerRoleStore
from yoyackbot.notices import localize
from yoyackbot.speed import SQLiteSpeedStore

LOGGER = logging.getLogger(__name__)
DENIED = "🚫 이 속도 화면은 연 사람만 쓸 수 있소. `/속도 설정`을 직접 여시오. 🙅"
EXPIRED = "⌛ 속도 화면 시간이 지났소. `/속도 설정`을 다시 여시오. 🔁"
FAILED = "⚠️ 속도 설정을 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧"
READ_FAILED = "⚠️ 속도 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"
TURNED_ON = "⚡✅ 빠른 모드를 켰소."
TURNED_OFF = "🐢✅ 빠른 모드를 껐소."
CLOSED = "👋 속도 화면을 닫았소."
EXPLAIN = "💡 켜면 이 서버의 요약·`!!말하자면`이 더 빨리 나오지만 Codex 사용량이 더 들 수 있소."
_SECONDS = 120


def speed_message(fast: bool) -> str:
    state = "⚡ 빠른 모드: 켜짐" if fast else "🐢 빠른 모드: 꺼짐(기본)"
    return f"{state}\n{EXPLAIN}\n🛠️ 켜기·끄기를 고르시오. 👇"


class Choose(discord.ui.Button["SpeedView"]):
    def __init__(self, fast: bool) -> None:
        super().__init__(
            label="켜기" if fast else "끄기",
            style=discord.ButtonStyle.primary if fast else discord.ButtonStyle.secondary,
        )
        self.fast = fast

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        if await view.check(interaction):
            await view.write(interaction, self.fast)


class Close(discord.ui.Button["SpeedView"]):
    def __init__(self) -> None:
        super().__init__(label="닫기", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        if not view.owned(interaction):
            await reject(interaction, DENIED)
            return
        view.finish()
        await interaction.response.edit_message(
            content=localize(interaction.guild_id, CLOSED),
            view=view,
        )


class SpeedView(discord.ui.View):
    def __init__(
        self, speeds: SQLiteSpeedStore, roles: ManagerRoleStore, guild_id: int, owner_id: int,
    ) -> None:
        super().__init__(timeout=_SECONDS)
        self.speeds = speeds
        self.roles = roles
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.expires_at = monotonic() + _SECONDS
        self.message: discord.Message | None = None
        for item in (Choose(True), Choose(False), Close()):
            self.add_item(item)

    def owned(self, interaction: discord.Interaction) -> bool:
        return interaction.guild_id == self.guild_id and interaction.user.id == self.owner_id

    def expired(self) -> bool:
        return self.is_finished() or monotonic() >= self.expires_at

    def finish(self) -> None:
        self.stop()
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def check(self, interaction: discord.Interaction) -> bool:
        """Opener, server, time limit and the 1.1.3 permission rule on every press."""
        if not self.owned(interaction):
            await reject(interaction, DENIED)
            return False
        if self.expired():
            await reject(interaction, EXPIRED)
            return False
        if not await allowed(interaction, self.roles):
            return False
        if self.expired():
            await reject(interaction, EXPIRED)
            return False
        return True

    async def write(self, interaction: discord.Interaction, fast: bool) -> None:
        try:
            await asyncio.to_thread(self.speeds.set, self.guild_id, fast)
        except Exception:  # noqa: BLE001
            LOGGER.warning("speed_save_failed")
            await reject(interaction, FAILED)
            return
        LOGGER.info("speed_saved fast=%s", "true" if fast else "false")
        self.finish()
        notice = TURNED_ON if fast else TURNED_OFF
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, f"{notice}\n{speed_message(fast)}"),
            view=self,
        )

    async def on_timeout(self) -> None:
        self.finish()
        if self.message is not None:
            try:
                await self.message.edit(content=localize(self.guild_id, EXPIRED), view=self)
            except discord.HTTPException:
                LOGGER.warning("speed_view_expired_edit_failed")


def install_speed_command(
    tree: app_commands.CommandTree, speeds: SQLiteSpeedStore, roles: ManagerRoleStore,
) -> None:
    group = command_group("속도", "요약봇 응답 속도 관리")

    @group.command(name="설정", description="이 서버에서 luna 빠른 모드를 켜고 끄오")
    @gated(roles)
    async def configure(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None  # gated() answers outside servers
        try:
            fast = await asyncio.to_thread(speeds.fast, guild.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("speed_read_failed")
            await reject(interaction, READ_FAILED)
            return
        view = SpeedView(speeds, roles, guild.id, interaction.user.id)
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, speed_message(fast)),
            view=view,
        )
        view.message = await interaction.original_response()

    tree.add_command(group)
