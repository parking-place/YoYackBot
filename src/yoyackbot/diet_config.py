"""`/돼지채널 설정`·`/돼지역할 설정` (1.4.3) and `/운동채널 설정`·`/운동역할 설정` (1.4.4): the
diet channel and role, and where exercise is read and for whom (the diet ones unless set), for
administrators and bot manager roles."""

from __future__ import annotations

import asyncio
import functools
import logging

import discord
from discord import app_commands

from yoyackbot.channel_config import allowed, command_group, gated, reject, valid_channel
from yoyackbot.diet import SQLiteDietStore
from yoyackbot.execution_config import (
    CLOSED,
    FAILED,
    INVALID_CHANNEL,
    INVALID_ROLE,
    READ_FAILED,
    SettingsView,
)
from yoyackbot.manager_roles import ManagerRoleStore
from yoyackbot.notices import localize
from yoyackbot.role_config import valid_role

LOGGER = logging.getLogger(__name__)
NO_CHANNEL = "🐷 식단 채널: 없음(재촉하지 않음)"
NO_ROLE = "🐷 식단 역할: 없음(재촉하지 않음)"
SCHEDULE_ON = "⏰ 매일 21:00에 역할을 부르고, 22:00에 안 올린 사람을 부르고, 22:30에 식단을 평가하오."
SCHEDULE_OFF = "💤 식단 채널과 역할을 모두 정해야 재촉을 시작하오."
MENTION_WARNING = (
    "⚠️ 봇이 이 역할을 멘션할 수 없소. 역할을 멘션 가능으로 바꾸거나 봇에 모든 역할 멘션 권한을 주시오. 🔧"
)
PRESS_SAVE = "💾 저장을 눌러 확정하시오. 👇"
CHANNEL_CLEARED = "🧹 식단 채널을 비웠소. 저장을 눌러 확정하시오. 👇"
ROLE_CLEARED = "🧹 식단 역할을 비웠소. 저장을 눌러 확정하시오. 👇"
CHANNEL_HINT = "🛠️ 채널을 고르고 저장하거나 해제하시오. 👇"
ROLE_HINT = "🛠️ 역할을 고르고 저장하거나 해제하시오. 👇"
NO_EXERCISE_CHANNEL = "🏃 운동 채널: 없음(식단 채널을 씀)"
NO_EXERCISE_ROLE = "🏃 운동 역할: 없음(돼지역할을 씀)"
EXERCISE_SCHEDULE = "📊 운동은 매일 22:30 식단 평가에서 함께 정산하고, 일요일에는 주간 훈수를 하오."
EXERCISE_CHANNEL_CLEARED = "🧹 운동 채널을 비웠소(식단 채널을 씀). 저장을 눌러 확정하시오. 👇"
EXERCISE_ROLE_CLEARED = "🧹 운동 역할을 비웠소(돼지역할을 씀). 저장을 눌러 확정하시오. 👇"


def can_mention(guild: discord.Guild, role_id: int, channel_id: int | None) -> bool:
    """A mentionable role, or the bot may mention every role in that channel."""
    role = guild.get_role(role_id)
    if role is None:
        return False
    if getattr(role, "mentionable", False):
        return True
    me = getattr(guild, "me", None)
    channel = guild.get_channel(channel_id) if channel_id is not None else None
    if me is None or channel is None:
        permissions = getattr(me, "guild_permissions", None)
    else:
        permissions = channel.permissions_for(me)
    return bool(getattr(permissions, "mention_everyone", False))


def status_message(guild: discord.Guild, channel_id: int | None, role_id: int | None) -> str:
    lines = [
        NO_CHANNEL if channel_id is None
        else f"🐷 식단 채널: {getattr(guild.get_channel(channel_id), 'mention', '삭제된 채널')}",
        NO_ROLE if role_id is None
        else f"🐷 식단 역할: {getattr(guild.get_role(role_id), 'mention', '삭제된 역할')}",
        SCHEDULE_ON if channel_id is not None and role_id is not None else SCHEDULE_OFF,
    ]
    if role_id is not None and not can_mention(guild, role_id, channel_id):
        lines.append(MENTION_WARNING)
    return "\n".join(lines)


def exercise_message(guild: discord.Guild, channel_id: int | None, role_id: int | None) -> str:
    return "\n".join([
        NO_EXERCISE_CHANNEL if channel_id is None
        else f"🏃 운동 채널: {getattr(guild.get_channel(channel_id), 'mention', '삭제된 채널')}",
        NO_EXERCISE_ROLE if role_id is None
        else f"🏃 운동 역할: {getattr(guild.get_role(role_id), 'mention', '삭제된 역할')}",
        EXERCISE_SCHEDULE,
    ])


class DietView(SettingsView):
    """Opener only, the 1.1.3 permission rule again on every press, 120 seconds."""

    def __init__(self, store: SQLiteDietStore, roles: ManagerRoleStore, guild_id: int,
                 owner_id: int, current: tuple[int | None, int | None], *, kind: str,
                 section: str = "diet") -> None:
        super().__init__(guild_id, owner_id, lambda interaction: allowed(interaction, roles))
        self.store = store
        self.kind = kind  # "channel" or "role"
        self.section = section  # "diet" or (1.4.4) "exercise"
        self.channel_id, self.role_id = current
        exercise = section == "exercise"
        if kind == "channel":
            pick: discord.ui.Select = discord.ui.ChannelSelect(
                placeholder="🏃 운동 기록을 읽을 텍스트 채널" if exercise else "🐷 식단을 올릴 텍스트 채널",
                channel_types=[discord.ChannelType.text], min_values=1, max_values=1,
            )
        else:
            pick = discord.ui.RoleSelect(
                placeholder="🏃 운동을 챙길 역할" if exercise else "🐷 식단 채널에서 부를 역할",
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

    def status(self, guild: discord.Guild) -> str:
        if self.section == "exercise":
            return exercise_message(guild, self.channel_id, self.role_id)
        return status_message(guild, self.channel_id, self.role_id)

    def _valid(self, guild: discord.Guild) -> bool:
        if self.kind == "channel":
            return self.channel_id is None or valid_channel(guild, self.channel_id)
        return self.role_id is None or valid_role(guild, self.role_id)

    async def _pick(self, select: discord.ui.Select, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        chosen = select.values[0].id
        if self.kind == "channel":
            if guild is None or not valid_channel(guild, chosen):
                await reject(interaction, INVALID_CHANNEL)
                return
            self.channel_id = chosen
        else:
            if guild is None or not valid_role(guild, chosen):
                await reject(interaction, INVALID_ROLE)
                return
            self.role_id = chosen
        await reject(interaction, f"{self.status(guild)}\n{PRESS_SAVE}")

    async def _clear(self, interaction: discord.Interaction) -> None:
        exercise = self.section == "exercise"
        if self.kind == "channel":
            self.channel_id = None
            await reject(interaction, EXERCISE_CHANNEL_CLEARED if exercise else CHANNEL_CLEARED)
        else:
            self.role_id = None
            await reject(interaction, EXERCISE_ROLE_CLEARED if exercise else ROLE_CLEARED)

    async def _save(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        if not self._valid(guild):
            await reject(interaction, INVALID_CHANNEL if self.kind == "channel" else INVALID_ROLE)
            return
        exercise = self.section == "exercise"
        setter = {
            ("diet", "channel"): self.store.set_channel, ("diet", "role"): self.store.set_role,
            ("exercise", "channel"): self.store.set_exercise_channel,
            ("exercise", "role"): self.store.set_exercise_role,
        }[self.section, self.kind]
        try:
            await asyncio.to_thread(setter, self.guild_id,
                                    self.channel_id if self.kind == "channel" else self.role_id)
            self.channel_id, self.role_id = await asyncio.to_thread(
                self.store.exercise_settings if exercise else self.store.settings, self.guild_id,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("diet_settings_save_failed kind=%s", self.kind)
            await reject(interaction, FAILED)
            return
        LOGGER.info("%s_settings_saved kind=%s channel=%s role=%s", self.section, self.kind,
                    self.channel_id is not None, self.role_id is not None)
        self.finish()
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, f"💾✅ 저장했소.\n{self.status(guild)}"),
            view=self,
        )

    async def _close(self, interaction: discord.Interaction) -> None:
        self.finish()
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, CLOSED), view=self,
        )


def install_diet_settings(
    tree: app_commands.CommandTree, store: SQLiteDietStore, roles: ManagerRoleStore,
) -> None:
    async def open_view(interaction: discord.Interaction, kind: str, section: str = "diet") -> None:
        guild = interaction.guild
        assert guild is not None  # gated() answers outside servers
        try:
            current = await asyncio.to_thread(
                store.exercise_settings if section == "exercise" else store.settings, guild.id,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("diet_settings_read_failed")
            await reject(interaction, READ_FAILED)
            return
        view = DietView(store, roles, guild.id, interaction.user.id, current, kind=kind, section=section)
        hint = CHANNEL_HINT if kind == "channel" else ROLE_HINT
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, f"{view.status(guild)}\n{hint}"),
            view=view,
        )
        view.message = await interaction.original_response()

    channel_group = command_group("돼지채널", "식단 채널 관리")

    @channel_group.command(name="설정", description="식단을 올리고 재촉할 채널을 정하오")
    @gated(roles)
    async def channel(interaction: discord.Interaction) -> None:
        await open_view(interaction, "channel")

    role_group = command_group("돼지역할", "식단 채널에서 부를 역할 관리")

    @role_group.command(name="설정", description="식단 채널에서 부를 역할을 정하오")
    @gated(roles)
    async def role(interaction: discord.Interaction) -> None:
        await open_view(interaction, "role")

    exercise_channel_group = command_group("운동채널", "운동 기록 채널 관리")

    @exercise_channel_group.command(name="설정", description="운동 기록을 읽을 채널을 정하오(기본: 식단 채널)")
    @gated(roles)
    async def exercise_channel(interaction: discord.Interaction) -> None:
        await open_view(interaction, "channel", "exercise")

    exercise_role_group = command_group("운동역할", "운동을 챙길 역할 관리")

    @exercise_role_group.command(name="설정", description="운동을 챙길 역할을 정하오(기본: 돼지역할)")
    @gated(roles)
    async def exercise_role(interaction: discord.Interaction) -> None:
        await open_view(interaction, "role", "exercise")

    for group in (channel_group, role_group, exercise_channel_group, exercise_role_group):
        tree.add_command(group)
