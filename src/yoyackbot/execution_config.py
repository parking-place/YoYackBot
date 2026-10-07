"""`/처형설정` (1.4.0): the 처형 log channel (admins and bot manager roles) and the roles that
may use `/처형` (administrators only)."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

import discord
from discord import app_commands

from yoyackbot.channel_config import allowed, command_group, gated, reject, valid_channel
from yoyackbot.execution import SQLiteExecutionStore
from yoyackbot.manager_roles import ManagerRoleStore
from yoyackbot.notices import localize
from yoyackbot.role_config import valid_role

LOGGER = logging.getLogger(__name__)
ADMIN_ONLY = "🚫 처형 역할은 서버 관리자만 정할 수 있소. 🙅"
DENIED = "🚫 이 설정 화면은 연 사람만 쓸 수 있소. 명령을 직접 여시오. 🙅"
EXPIRED = "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁"
FAILED = "⚠️ 설정을 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧"
READ_FAILED = "⚠️ 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"
INVALID_CHANNEL = "⚠️ 봇이 그 채널을 보고 글을 쓸 수 있어야 하오. 다른 텍스트 채널을 고르시오. 🙅"
INVALID_ROLE = "⚠️ 고를 수 없는 역할이 있소. @everyone과 봇·연동이 관리하는 역할은 고를 수 없소. 🙅"
CLOSED = "👋 설정 화면을 닫았소."
_SECONDS = 120


AUDIT_WARNING = "⚠️ 봇에 감사 로그 보기 권한이 없어 지금은 처형 로그를 올릴 수 없소. 🔧"


def channel_message(guild: discord.Guild, channel_id: int | None) -> str:
    if channel_id is None:
        text = "📜 처형 로그 채널: 없음(로그를 올리지 않음)"
    else:
        channel = guild.get_channel(channel_id)
        text = f"📜 처형 로그 채널: {getattr(channel, 'mention', '삭제된 채널')}"
    permissions = getattr(getattr(guild, "me", None), "guild_permissions", None)
    if permissions is not None and not getattr(permissions, "view_audit_log", True):
        text += f"\n{AUDIT_WARNING}"
    return text


def roles_message(guild: discord.Guild, role_ids: frozenset[int] | set[int]) -> str:
    chosen = sorted(role_ids)
    shown = [getattr(guild.get_role(role_id), "mention", "삭제된 역할") for role_id in chosen[:20]]
    suffix = f" 외 {len(chosen) - 20}개" if len(chosen) > 20 else ""
    listing = ", ".join(shown) + suffix if shown else "없음(관리자만 사용)"
    return f"⚔️ 처형 역할 {len(chosen)}개: {listing}"


async def admin_allowed(interaction: discord.Interaction) -> bool:
    """Server administrators (or the owner) only, read from current membership; answers privately."""
    guild = interaction.guild
    if guild is None:
        await reject(interaction, ADMIN_ONLY)
        return False
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    member = interaction.user
    fetch_member = getattr(guild, "fetch_member", None)
    if fetch_member is not None:
        try:
            member = await fetch_member(interaction.user.id)
        except discord.HTTPException:
            member = None
    permissions = getattr(member, "guild_permissions", None)
    if member is not None and (
        getattr(guild, "owner_id", None) == member.id
        or (permissions is not None and permissions.administrator)
    ):
        return True
    await reject(interaction, ADMIN_ONLY)
    return False


def admin_only(
    callback: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(callback)
    async def run(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
        if await admin_allowed(interaction):
            return await callback(interaction, *args, **kwargs)
        return None

    run.__yoyack_gated__ = True  # type: ignore[attr-defined] - checked at run time, stricter
    return run


class SettingsView(discord.ui.View):
    """Opener only, the permission rule again on every press, 120 seconds."""

    def __init__(self, guild_id: int, owner_id: int,
                 check: Callable[[discord.Interaction], Awaitable[bool]]) -> None:
        super().__init__(timeout=_SECONDS)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.check = check
        self.expires_at = monotonic() + _SECONDS
        self.message: discord.Message | None = None

    def finish(self) -> None:
        self.stop()
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id or interaction.user.id != self.owner_id:
            await reject(interaction, DENIED)
            return False
        if self.is_finished() or monotonic() >= self.expires_at:
            await reject(interaction, EXPIRED)
            return False
        permitted = await self.check(interaction)
        if permitted and (self.is_finished() or monotonic() >= self.expires_at):
            await reject(interaction, EXPIRED)
            return False
        return permitted

    async def on_timeout(self) -> None:
        self.finish()
        if self.message is not None:
            try:
                await self.message.edit(content=localize(self.guild_id, EXPIRED), view=self)
            except discord.HTTPException:
                LOGGER.warning("execution_settings_view_expired_edit_failed")


class ChannelView(SettingsView):
    def __init__(self, store: SQLiteExecutionStore, roles: ManagerRoleStore, guild_id: int,
                 owner_id: int, current: int | None) -> None:
        super().__init__(guild_id, owner_id, lambda interaction: allowed(interaction, roles))
        self.store = store
        self.draft = current
        pick = discord.ui.ChannelSelect(
            placeholder="📜 처형 로그를 올릴 텍스트 채널", channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1,
        )
        pick.callback = functools.partial(self._pick, pick)
        self.add_item(pick)
        for label, style, handler in (
            ("저장", discord.ButtonStyle.success, self._save),
            ("해제", discord.ButtonStyle.secondary, self._clear),
            ("닫기", discord.ButtonStyle.danger, self._close),
        ):
            button = discord.ui.Button(label=label, style=style)
            button.callback = handler
            self.add_item(button)

    async def _pick(self, select: discord.ui.ChannelSelect, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        chosen = select.values[0].id
        if guild is None or not valid_channel(guild, chosen):
            await reject(interaction, INVALID_CHANNEL)
            return
        self.draft = chosen
        await reject(interaction, f"{channel_message(guild, chosen)}\n💾 저장을 눌러 확정하시오. 👇")

    async def _clear(self, interaction: discord.Interaction) -> None:
        self.draft = None
        await reject(interaction, "🧹 처형 로그를 올리지 않게 했소. 저장을 눌러 확정하시오. 👇")

    async def _save(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        if self.draft is not None and not valid_channel(guild, self.draft):
            await reject(interaction, INVALID_CHANNEL)
            return
        try:
            await asyncio.to_thread(self.store.set_log_channel, self.guild_id, self.draft)
        except Exception:  # noqa: BLE001
            LOGGER.warning("execution_channel_save_failed")
            await reject(interaction, FAILED)
            return
        LOGGER.info("execution_channel_saved set=%s", "true" if self.draft else "false")
        self.finish()
        await interaction.edit_original_response(
            content=localize(
                interaction.guild_id,
                f"💾✅ 저장했소.\n{channel_message(guild, self.draft)}",
            ),
            view=self,
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        self.finish()
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, CLOSED),
            view=self,
        )


class RolesView(SettingsView):
    def __init__(self, store: SQLiteExecutionStore, guild_id: int, owner_id: int,
                 current: frozenset[int]) -> None:
        super().__init__(guild_id, owner_id, admin_allowed)
        self.store = store
        self.draft = set(current)
        pick = discord.ui.RoleSelect(placeholder="⚔️ 처형 역할로 쓸 역할(고른 것으로 바뀜)",
                                     min_values=1, max_values=25)
        pick.callback = functools.partial(self._pick, pick)
        self.add_item(pick)
        for label, style, handler in (
            ("저장", discord.ButtonStyle.success, self._save),
            ("전체 해제", discord.ButtonStyle.secondary, self._clear),
            ("닫기", discord.ButtonStyle.danger, self._close),
        ):
            button = discord.ui.Button(label=label, style=style)
            button.callback = handler
            self.add_item(button)

    async def _pick(self, select: discord.ui.RoleSelect, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        chosen = {role.id for role in select.values}
        if guild is None or not all(valid_role(guild, role_id) for role_id in chosen):
            await reject(interaction, INVALID_ROLE)
            return
        self.draft = chosen
        await reject(interaction, f"{roles_message(guild, chosen)}\n💾 저장을 눌러 확정하시오. 👇")

    async def _clear(self, interaction: discord.Interaction) -> None:
        self.draft = set()
        await reject(interaction, "🧹 처형 역할을 비웠소(관리자만 사용). 저장을 눌러 확정하시오. 👇")

    async def _save(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        draft = {role_id for role_id in self.draft if guild.get_role(role_id) is not None}
        if not all(valid_role(guild, role_id) for role_id in draft):
            await reject(interaction, INVALID_ROLE)
            return
        try:
            await asyncio.to_thread(self.store.set_roles, self.guild_id, draft)
        except Exception:  # noqa: BLE001
            LOGGER.warning("execution_roles_save_failed")
            await reject(interaction, FAILED)
            return
        LOGGER.info("execution_roles_saved count=%d", len(draft))
        self.finish()
        await interaction.edit_original_response(
            content=localize(
                interaction.guild_id,
                f"💾✅ 저장했소.\n{roles_message(guild, draft)}",
            ),
            view=self,
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        self.finish()
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, CLOSED),
            view=self,
        )


def install_execution_settings(
    tree: app_commands.CommandTree, store: SQLiteExecutionStore, roles: ManagerRoleStore,
) -> None:
    group = command_group("처형설정", "처형 로그 채널과 처형 역할 관리")

    @group.command(name="채널관리", description="처형(타임아웃) 로그를 올릴 채널을 정하오")
    @gated(roles)
    async def channel(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None  # gated() answers outside servers
        try:
            current = await asyncio.to_thread(store.log_channel, guild.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("execution_settings_read_failed")
            await reject(interaction, READ_FAILED)
            return
        view = ChannelView(store, roles, guild.id, interaction.user.id, current)
        await interaction.edit_original_response(
            content=localize(
                interaction.guild_id,
                f"{channel_message(guild, current)}\n🛠️ 채널을 고르고 저장하거나 해제하시오. 👇",
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    @group.command(name="관리역할", description="/처형을 쓸 수 있는 역할을 정하오(관리자만)")
    @admin_only
    async def execution_roles(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        try:
            current = await asyncio.to_thread(store.roles, guild.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("execution_settings_read_failed")
            await reject(interaction, READ_FAILED)
            return
        view = RolesView(store, guild.id, interaction.user.id, current)
        await interaction.edit_original_response(
            content=localize(
                interaction.guild_id,
                f"{roles_message(guild, current)}\n🛠️ 역할을 고르고 저장하시오. 👑 관리자는 언제나 쓸 수 있소. 👇",
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    tree.add_command(group)
