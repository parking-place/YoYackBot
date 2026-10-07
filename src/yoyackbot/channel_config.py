"""Guild-scoped watched-channel selection; slash commands are for admins and manager roles."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol

import discord
from discord import app_commands

from yoyackbot.notices import localize

if TYPE_CHECKING:
    from yoyackbot.manager_roles import ManagerRoleStore
    from yoyackbot.role_config import RoleSettingsView

LOGGER = logging.getLogger(__name__)
DENIED = "🚫 이 설정 화면은 연 사람만 쓸 수 있소. `/채널 설정`을 직접 여시오. 🙅"
GUILD_ONLY = "🏠 서버 안에서만 쓸 수 있소. 🙅"
NOT_ALLOWED = "🔒 이 명령은 관리자나 봇 관리 역할만 쓸 수 있소. 🛡️"
# Bot tokens cannot grant command access per role, so every slash command stays visible to anyone
# who may use application commands and the bot itself decides who may run it (1.1.3).
SLASH_PERMISSIONS = discord.Permissions(use_application_commands=True)
INVALID = "⚠️ 봇이 접근할 수 있는 서버의 텍스트 채널만 고르시오. 📡"


class WatchStore(Protocol):
    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]: ...

    def get(self, guild_id: int) -> frozenset[int]: ...

    def version(self, guild_id: int) -> int: ...

    def replace(
        self, guild_id: int, channel_ids: frozenset[int], *, expected_version: int | None = None,
        authorize: Callable[[frozenset[int] | None], bool] | None = None,
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
        self._lock = RLock()

    def get(self, guild_id: int) -> frozenset[int]:
        with self._lock:
            return self._channels.get(guild_id, frozenset())

    def snapshot(self, guild_id: int) -> tuple[int, frozenset[int]]:
        with self._lock:
            return self.version(guild_id), self.get(guild_id)

    def version(self, guild_id: int) -> int:
        with self._lock:
            return self._versions.get(guild_id, 0)

    def replace(
        self, guild_id: int, channel_ids: frozenset[int], *, expected_version: int | None = None,
        authorize: Callable[[frozenset[int] | None], bool] | None = None,
    ) -> int:
        with self._lock:
            if authorize is not None and not authorize(None):
                raise PermissionError("Settings write authorization denied")
            if expected_version is not None and expected_version != self.version(guild_id):
                raise ConcurrentUpdate
            if self.get(guild_id) == channel_ids:
                return self.version(guild_id)
            self._channels[guild_id] = channel_ids
            self._versions[guild_id] = self.version(guild_id) + 1
            return self.version(guild_id)

    def remove_channel(self, guild_id: int, channel_id: int) -> bool:
        with self._lock:
            current = self.get(guild_id)
            if channel_id not in current:
                return False
            self.replace(guild_id, current - {channel_id})
            return True

    def remove_guild(self, guild_id: int) -> None:
        with self._lock:
            self._channels.pop(guild_id, None)
            self._versions.pop(guild_id, None)


def may_manage(member: object, manager_roles: frozenset[int]) -> bool:
    """Administrators and channel managers (as before 1.1.2a), or holders of a manager role."""
    permissions = getattr(member, "guild_permissions", None)
    if permissions is not None and (permissions.administrator or permissions.manage_channels):
        return True
    return any(getattr(role, "id", None) in manager_roles for role in getattr(member, "roles", ()))


async def allowed(interaction: discord.Interaction, roles: ManagerRoleStore) -> bool:
    """Decide at run time and answer the caller privately when the answer is no."""
    guild = interaction.guild
    if guild is None:
        await reject(interaction, GUILD_ONLY)
        return False
    # A SQLite writer can wait for seconds. Acknowledge before any store access.
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    try:
        manager_roles = await asyncio.to_thread(roles.get, guild.id)
    except Exception:  # noqa: BLE001 - administrators keep working if the role table is unreadable
        LOGGER.warning("manager_roles_read_failed")
        manager_roles = frozenset()
    if await current_permission(interaction, manager_roles):
        return True
    await reject(interaction, NOT_ALLOWED)
    return False


async def current_permission(
    interaction: discord.Interaction, manager_roles: frozenset[int],
) -> bool:
    """Check current Discord membership without reading settings or sending a response."""
    guild = interaction.guild
    if guild is None:
        return False
    get_role = getattr(guild, "get_role", None)
    if get_role is not None:
        manager_roles = frozenset(role_id for role_id in manager_roles if get_role(role_id) is not None)
    # This client disables its member cache; a cache miss does not mean the caller left.
    fetch_member = getattr(guild, "fetch_member", None)
    member = interaction.user
    if fetch_member is not None:
        try:
            member = await fetch_member(interaction.user.id)
        except discord.HTTPException:
            return False
    return member is not None and may_manage(member, manager_roles)


def write_authorizer(
    interaction: discord.Interaction, roles: ManagerRoleStore,
    view: ChannelSettingsView | RoleSettingsView,
    valid_draft: Callable[[], bool],
) -> Callable[[frozenset[int] | None], bool]:
    """Recheck permission after the worker acquired its write lock, with no SQLite reread."""
    loop = asyncio.get_running_loop()

    async def check(manager_roles: frozenset[int]) -> bool:
        if (view.is_finished() or monotonic() >= view.expires_at
                or interaction.guild_id != view.guild_id or interaction.user.id != view.owner_id):
            return False
        permitted = await current_permission(interaction, manager_roles)
        if not permitted or view.is_finished() or monotonic() >= view.expires_at:
            return False
        if not valid_draft():
            raise ConcurrentUpdate
        return True

    def authorize(manager_roles: frozenset[int] | None) -> bool:
        # Only the development MemoryWatchStore lacks a roles table. Its separate role store
        # can be read on this worker; SQLite and the locked role adapter always pass their set.
        if manager_roles is None:
            manager_roles = roles.get(view.guild_id)
        future = asyncio.run_coroutine_threadsafe(check(manager_roles), loop)
        try:
            return future.result(timeout=10)
        except ConcurrentUpdate:
            raise
        except Exception:  # noqa: BLE001 - fail closed; never keep a transaction waiting forever
            future.cancel()
            LOGGER.warning("settings_write_authorization_failed")
            return False

    return authorize


def command_group(name: str, description: str) -> app_commands.Group:
    """A server-only slash command group, visible to application command users."""
    return app_commands.Group(
        name=name, description=description, guild_only=True, default_permissions=SLASH_PERMISSIONS,
    )


def gated(
    roles: ManagerRoleStore,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Run a slash command callback only for administrators and manager roles."""
    def decorate(callback: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(callback)
        async def run(interaction: discord.Interaction, *args: Any, **kwargs: Any) -> Any:
            if await allowed(interaction, roles):
                return await callback(interaction, *args, **kwargs)
            return None

        run.__yoyack_gated__ = True  # type: ignore[attr-defined]
        return run
    return decorate


def bot_command(roles: ManagerRoleStore) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """The same rule for a future top-level slash command."""
    def decorate(callback: Callable[..., Any]) -> Callable[..., Any]:
        return app_commands.guild_only()(
            app_commands.default_permissions(use_application_commands=True)(gated(roles)(callback))
        )
    return decorate


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
    return f"📡 현재 주시 채널 {len(selected)}개: {listing}"


async def reject(interaction: discord.Interaction, message: str) -> None:
    """An ephemeral notice, in the server's own wording when its tone has notices (1.4.0)."""
    message = localize(interaction.guild_id, message)
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


class AddChannels(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="➕ 주시할 텍스트 채널 추가 (한 번에 최대 25개)",
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
        await reject(interaction,
            f"{selection_summary(guild, view.draft)}\n💾 저장을 눌러 확정하시오. 👇",
        )


class RemoveChannels(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            placeholder="➖ 주시 목록에서 텍스트 채널 제거",
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
        await reject(interaction,
            f"{selection_summary(guild, view.draft)}\n💾 저장을 눌러 확정하시오. 👇",
        )


class ClearChannels(discord.ui.Button["ChannelSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="전체 해제", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.draft.clear()
        await reject(interaction, "🧹 목록을 비웠소. 저장을 눌러 확정하시오. 👇")


class SaveChannels(discord.ui.Button["ChannelSettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="저장", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        async with view.save_lock:
            await self._save(interaction, view)

    async def _save(self, interaction: discord.Interaction, view: ChannelSettingsView) -> None:
        if not await view.interaction_check(interaction):
            return
        guild = interaction.guild
        draft = frozenset(view.draft)
        if guild is None or not valid_selection(guild, draft):
            await reject(interaction, INVALID)
            return
        try:
            await asyncio.to_thread(
                view.store.replace, view.guild_id, draft, expected_version=view.original_version,
                authorize=write_authorizer(
                    interaction, view.roles, view, lambda: valid_selection(guild, draft),
                ),
            )
        except PermissionError:
            await reject(interaction, NOT_ALLOWED)
            return
        except ConcurrentUpdate:
            await reject(interaction, "🔄 다른 사람이 설정을 바꾸었소. 명령을 다시 열어 확인하시오. 👀")
            return
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_save_failed")
            await reject(interaction, "⚠️ 설정을 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧")
            return
        LOGGER.info(
            "watched_channels_saved at=%s count=%d",
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), len(draft),
        )
        view.draft = set(draft)
        view.stop()
        for item in view.children:
            item.disabled = True
        await interaction.edit_original_response(
            content=localize(
                interaction.guild_id,
                f"💾✅ 주시 채널 {len(draft)}개를 저장했소. 🎉\n{selection_summary(guild, draft)}",
            ),
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
        if interaction.response.is_done():
            await interaction.edit_original_response(
                content=localize(interaction.guild_id, "↩️ 설정 변경을 취소했소. 🙆"),
                view=self.view,
            )
        else:
            await interaction.response.edit_message(
                content=localize(interaction.guild_id, "↩️ 설정 변경을 취소했소. 🙆"),
                view=self.view,
            )


class ChannelSettingsView(discord.ui.View):
    def __init__(
        self, store: WatchStore, guild_id: int, owner_id: int, roles: ManagerRoleStore,
        *, snapshot: tuple[int, frozenset[int]],
    ) -> None:
        super().__init__(timeout=120)
        self.store = store
        self.roles = roles
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.original_version, original = snapshot
        self.draft = set(original)
        self.expires_at = monotonic() + 120
        self.save_lock = asyncio.Lock()
        self.message: discord.Message | None = None
        self.add_item(AddChannels())
        self.add_item(RemoveChannels())
        self.add_item(ClearChannels())
        self.add_item(SaveChannels())
        self.add_item(CancelChannels())

    async def on_timeout(self) -> None:
        self.stop()
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content=localize(self.guild_id, "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁"),
                    view=self,
                )
            except discord.HTTPException:
                LOGGER.warning("watched_channel_view_expired_edit_failed")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != self.guild_id or interaction.user.id != self.owner_id:
            await reject(interaction, DENIED)
            return False
        if self.is_finished() or monotonic() >= self.expires_at:
            await reject(interaction, "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁")
            return False
        permitted = await allowed(interaction, self.roles)
        if permitted and (self.is_finished() or monotonic() >= self.expires_at):
            await reject(interaction, "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁")
            return False
        return permitted


def install_channel_commands(
    tree: app_commands.CommandTree, store: WatchStore, roles: ManagerRoleStore,
) -> None:
    group = command_group("채널", "주시 채널 관리")

    @group.command(name="설정", description="요약봇이 주시할 텍스트 채널을 고르오")
    @gated(roles)
    async def configure(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None  # gated() answers outside servers
        try:
            snapshot = await asyncio.to_thread(store.snapshot, guild.id)
            if not await allowed(interaction, roles):
                return
            view = ChannelSettingsView(
                store, guild.id, interaction.user.id, roles, snapshot=snapshot,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_read_failed")
            await reject(interaction, "⚠️ 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧")
            return
        await interaction.edit_original_response(
            content=localize(
                interaction.guild_id,
                f"{selection_summary(guild, view.draft)}\n🛠️ 추가·제거 후 저장하거나 전체 해제를 고르시오. 👇",
            ),
            view=view,
        )
        view.message = await interaction.original_response()

    tree.add_command(group)
