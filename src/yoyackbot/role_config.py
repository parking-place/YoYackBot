"""`/관리권한 설정`: choose which server roles may use the bot's slash commands (1.1.3)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime

import discord
from discord import app_commands

from yoyackbot.channel_config import (
    DENIED,
    ConcurrentUpdate,
    allowed,
    command_group,
    gated,
    reject,
)
from yoyackbot.manager_roles import ManagerRoleStore

LOGGER = logging.getLogger(__name__)
INVALID_ROLE = "고를 수 없는 역할이 있소. @everyone과 봇·연동이 관리하는 역할은 고를 수 없소."


def valid_role(guild: discord.Guild, role_id: int) -> bool:
    role = guild.get_role(role_id)
    return role is not None and not role.is_default() and not role.managed


def valid_roles(guild: discord.Guild, role_ids: Iterable[int]) -> bool:
    return all(valid_role(guild, role_id) for role_id in role_ids)


def role_summary(guild: discord.Guild, role_ids: Iterable[int]) -> str:
    chosen = sorted(set(role_ids))
    shown = [getattr(guild.get_role(role_id), "mention", "삭제된 역할") for role_id in chosen[:20]]
    suffix = f" 외 {len(chosen) - 20}개" if len(chosen) > 20 else ""
    listing = ", ".join(shown) + suffix if shown else "없음(관리자만 사용)"
    return f"현재 봇 관리 역할 {len(chosen)}개: {listing}"


def _view(item: discord.ui.Item[RoleSettingsView]) -> RoleSettingsView:
    view = item.view
    assert isinstance(view, RoleSettingsView)
    return view


class AddRoles(discord.ui.RoleSelect["RoleSettingsView"]):
    def __init__(self) -> None:
        super().__init__(placeholder="봇 관리 역할 추가 (한 번에 최대 25개)", min_values=1, max_values=25)

    async def callback(self, interaction: discord.Interaction) -> None:
        view, guild = _view(self), interaction.guild
        chosen = {role.id for role in self.values}
        if guild is None or not valid_roles(guild, chosen):
            await reject(interaction, INVALID_ROLE)
            return
        view.draft.update(chosen)
        await interaction.response.send_message(
            f"{role_summary(guild, view.draft)}\n저장을 눌러 확정하시오.", ephemeral=True,
        )


class RemoveRoles(discord.ui.RoleSelect["RoleSettingsView"]):
    def __init__(self) -> None:
        super().__init__(placeholder="봇 관리 역할에서 제거", min_values=1, max_values=25)

    async def callback(self, interaction: discord.Interaction) -> None:
        view, guild = _view(self), interaction.guild
        if guild is None:
            await reject(interaction, INVALID_ROLE)
            return
        view.draft.difference_update(role.id for role in self.values)
        await interaction.response.send_message(
            f"{role_summary(guild, view.draft)}\n저장을 눌러 확정하시오.", ephemeral=True,
        )


class ClearRoles(discord.ui.Button["RoleSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="전체 해제", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        _view(self).draft.clear()
        await interaction.response.send_message(
            "목록을 비웠소(관리자만 쓰게 됨). 저장을 눌러 확정하시오.", ephemeral=True,
        )


class SaveRoles(discord.ui.Button["RoleSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="저장", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view, guild = _view(self), interaction.guild
        if guild is None or not valid_roles(guild, view.draft):
            await reject(interaction, INVALID_ROLE)
            return
        try:
            view.roles.replace(
                view.guild_id, frozenset(view.draft), expected_version=view.original_version
            )
        except ConcurrentUpdate:
            await reject(interaction, "다른 사람이 설정을 바꾸었소. 명령을 다시 열어 확인하시오.")
            return
        except Exception:  # noqa: BLE001
            LOGGER.warning("manager_roles_save_failed")
            await reject(interaction, "설정을 저장하지 못했소. 잠시 후 다시 시도하시오.")
            return
        LOGGER.info(
            "manager_roles_saved at=%s count=%d",
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), len(view.draft),
        )
        view.stop()
        for item in view.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            content=f"봇 관리 역할 {len(view.draft)}개를 저장했소.\n{role_summary(guild, view.draft)}",
            view=view,
        )


class CancelRoles(discord.ui.Button["RoleSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="취소", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = _view(self)
        view.stop()
        for item in view.children:
            item.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="설정 변경을 취소했소.", view=view)


class RoleSettingsView(discord.ui.View):
    def __init__(self, roles: ManagerRoleStore, guild_id: int, owner_id: int) -> None:
        super().__init__(timeout=120)
        self.roles = roles
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.original_version, original = roles.snapshot(guild_id)
        self.draft = set(original)
        self.message: discord.Message | None = None
        for item in (AddRoles(), RemoveRoles(), ClearRoles(), SaveRoles(), CancelRoles()):
            self.add_item(item)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        if self.message is not None:
            try:
                await self.message.edit(content="설정 시간이 지났소. 명령을 다시 여시오.", view=self)
            except discord.HTTPException:
                LOGGER.warning("manager_roles_view_expired_edit_failed")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id or interaction.user.id != self.owner_id:
            await reject(interaction, DENIED)
            return False
        return await allowed(interaction, self.roles)


def install_role_commands(tree: app_commands.CommandTree, roles: ManagerRoleStore) -> None:
    group = command_group("관리권한", "봇 관리 역할 관리")

    @group.command(name="설정", description="요약봇 슬래시 명령어를 쓸 수 있는 역할을 고르오")
    @gated(roles)
    async def configure(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None  # gated() answers outside servers
        try:
            view = RoleSettingsView(roles, guild.id, interaction.user.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("manager_roles_read_failed")
            await reject(interaction, "설정을 읽지 못했소. 잠시 후 다시 시도하시오.")
            return
        await interaction.response.send_message(
            f"{role_summary(guild, view.draft)}\n추가·제거 후 저장하거나 전체 해제를 고르시오. "
            "관리자는 언제나 쓸 수 있소.",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    tree.add_command(group)
