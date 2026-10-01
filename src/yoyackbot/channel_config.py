"""Guild-scoped watched-channel selection; Discord decides who may run slash commands."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol

import discord
from discord import app_commands

LOGGER = logging.getLogger(__name__)
DENIED = "이 설정 화면은 연 사람만 쓸 수 있소. `/채널 설정`을 직접 여시오."
GUILD_ONLY = "서버 안에서만 쓸 수 있소."
# Every slash command (now and later): anyone Discord lets use application commands, from the start.
SLASH_PERMISSIONS = discord.Permissions(use_application_commands=True)
INVALID = "봇이 접근할 수 있는 서버의 텍스트 채널만 고르시오."


class WatchStore(Protocol):
    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]: ...

    def get(self, guild_id: int) -> frozenset[int]: ...

    def version(self, guild_id: int) -> int: ...

    def replace(
        self, guild_id: int, channel_ids: frozenset[int], *, expected_version: int | None = None
    ) -> int: ...

    def remove_channel(self, guild_id: int, channel_id: int) -> bool: ...

    def remove_guild(self, guild_id: int) -> None: ...


class ConcurrentUpdate(RuntimeError):
    """The watched-channel list changed while a selection was open."""


class MemoryWatchStore:
    """Development adapter; 0.1.0-P3 replaces it with SQLite persistence."""

    def __init__(self) -> None:
        self._channels: dict[int, frozenset[int]] = {}
        self._versions: dict[int, int] = {}

    def get(self, guild_id: int) -> frozenset[int]:
        return self._channels.get(guild_id, frozenset())

    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]:
        return self.version(guild_id), self.get(guild_id)

    def version(self, guild_id: int) -> int:
        return self._versions.get(guild_id, 0)

    def replace(
        self, guild_id: int, channel_ids: frozenset[int], *, expected_version: int | None = None
    ) -> int:
        if expected_version is not None and expected_version != self.version(guild_id):
            raise ConcurrentUpdate
        if self.get(guild_id) == channel_ids:
            return self.version(guild_id)
        self._channels[guild_id] = channel_ids
        self._versions[guild_id] = self.version(guild_id) + 1
        return self.version(guild_id)

    def remove_channel(self, guild_id: int, channel_id: int) -> bool:
        current = self.get(guild_id)
        if channel_id not in current:
            return False
        self.replace(guild_id, current - {channel_id})
        return True

    def remove_guild(self, guild_id: int) -> None:
        self._channels.pop(guild_id, None)
        self._versions.pop(guild_id, None)


def member_group(name: str, description: str) -> app_commands.Group:
    """A slash command group open to everyone with Use Application Commands, in servers only."""
    return app_commands.Group(
        name=name, description=description, guild_only=True, default_permissions=SLASH_PERMISSIONS,
    )


def member_command[T: Callable[..., object]](function: T) -> T:
    """The same rule for a top-level slash command; server admins may still narrow it."""
    return app_commands.guild_only()(
        app_commands.default_permissions(use_application_commands=True)(function)
    )


def valid_channel(guild: discord.Guild, channel_id: int) -> bool:
    channel = guild.get_channel(channel_id)
    member = guild.me
    if not isinstance(channel, discord.TextChannel) or member is None:
        return False
    permissions = channel.permissions_for(member)
    return bool(
        permissions.view_channel and permissions.read_message_history and permissions.send_messages
    )


def valid_selection(guild: discord.Guild, channel_ids: Iterable[int]) -> bool:
    return all(valid_channel(guild, channel_id) for channel_id in channel_ids)


def selection_summary(guild: discord.Guild, channel_ids: Iterable[int]) -> str:
    selected = sorted(set(channel_ids))
    shown = []
    for channel_id in selected[:20]:
        channel = guild.get_channel(channel_id)
        shown.append(getattr(channel, "mention", "삭제된 채널"))
    suffix = f" 외 {len(selected) - 20}개" if len(selected) > 20 else ""
    listing = ", ".join(shown) + suffix if shown else "없음"
    return f"현재 주시 채널 {len(selected)}개: {listing}"


async def reject(interaction: discord.Interaction, message: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class AddChannels(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="주시할 텍스트 채널 추가 (한 번에 최대 25개)",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=25,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, ChannelSettingsView)
        guild = interaction.guild
        if guild is None:
            await reject(interaction, INVALID)
            return
        chosen = {channel.id for channel in self.values}
        if not valid_selection(guild, chosen):
            await reject(interaction, INVALID)
            return
        view.draft.update(chosen)
        await interaction.response.send_message(
            f"{selection_summary(guild, view.draft)}\n저장을 눌러 확정하시오.",
            ephemeral=True,
        )


class RemoveChannels(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="주시 목록에서 텍스트 채널 제거",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=25,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert isinstance(view, ChannelSettingsView)
        guild = interaction.guild
        if guild is None:
            await reject(interaction, INVALID)
            return
        view.draft.difference_update(channel.id for channel in self.values)
        await interaction.response.send_message(
            f"{selection_summary(guild, view.draft)}\n저장을 눌러 확정하시오.",
            ephemeral=True,
        )


class ClearChannels(discord.ui.Button["ChannelSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="전체 해제", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.draft.clear()
        await interaction.response.send_message("목록을 비웠소. 저장을 눌러 확정하시오.", ephemeral=True)


class SaveChannels(discord.ui.Button["ChannelSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="저장", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        guild = interaction.guild
        if guild is None or not valid_selection(guild, view.draft):
            await reject(interaction, INVALID)
            return
        try:
            view.store.replace(
                view.guild_id, frozenset(view.draft), expected_version=view.original_version
            )
        except ConcurrentUpdate:
            await reject(interaction, "다른 사람이 설정을 바꾸었소. 명령을 다시 열어 확인하시오.")
            return
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_save_failed")
            await reject(interaction, "설정을 저장하지 못했소. 잠시 후 다시 시도하시오.")
            return
        LOGGER.info(
            "watched_channels_saved at=%s count=%d",
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), len(view.draft),
        )
        view.stop()
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"주시 채널 {len(view.draft)}개를 저장했소.\n{selection_summary(guild, view.draft)}",
            view=view,
        )


class CancelChannels(discord.ui.Button["ChannelSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="취소", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.stop()
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(content="설정 변경을 취소했소.", view=self.view)


class ChannelSettingsView(discord.ui.View):
    def __init__(self, store: WatchStore, guild_id: int, owner_id: int) -> None:
        super().__init__(timeout=120)
        self.store = store
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.original_version, original = store.snapshot(guild_id)
        self.draft = set(original)
        self.message: discord.Message | None = None
        self.add_item(AddChannels())
        self.add_item(RemoveChannels())
        self.add_item(ClearChannels())
        self.add_item(SaveChannels())
        self.add_item(CancelChannels())

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="설정 시간이 지났소. 명령을 다시 여시오.", view=self)
            except discord.HTTPException:
                LOGGER.warning("watched_channel_view_expired_edit_failed")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id or interaction.user.id != self.owner_id:
            await reject(interaction, DENIED)
            return False
        return True


def install_channel_commands(tree: app_commands.CommandTree, store: WatchStore) -> None:
    group = member_group("채널", "주시 채널 관리")

    @group.command(name="설정", description="요약봇이 주시할 텍스트 채널을 고르오")
    async def configure(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await reject(interaction, GUILD_ONLY)
            return
        try:
            view = ChannelSettingsView(store, guild.id, interaction.user.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_read_failed")
            await reject(interaction, "설정을 읽지 못했소. 잠시 후 다시 시도하시오.")
            return
        await interaction.response.send_message(
            f"{selection_summary(guild, view.draft)}\n추가·제거 후 저장하거나 전체 해제를 고르시오.",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    tree.add_command(group)
