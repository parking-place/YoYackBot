"""`/말투`: see, edit or reset this server's tone and personality (1.3.0)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from time import monotonic

import discord
from discord import app_commands

from yoyackbot.channel_config import ConcurrentUpdate, allowed, bot_command, reject
from yoyackbot.manager_roles import ManagerRoleStore
from yoyackbot.summary_prompt import TONE_DEFAULT, TONE_LIMIT
from yoyackbot.tone import SQLiteToneStore, ToneTooLong, clean_tone

LOGGER = logging.getLogger(__name__)
DENIED = "🚫 이 말투 화면은 연 사람만 쓸 수 있소. `/말투`를 직접 여시오. 🙅"
EXPIRED = "⌛ 말투 화면 시간이 지났소. `/말투`를 다시 여시오. 🔁"
CHANGED = "🔄 다른 사람이 말투를 바꾸었소. `/말투`를 다시 열어 확인하시오. 👀"
EMPTY = f"✂️ 말투는 1자 이상 {TONE_LIMIT:,}자 이하로 쓰시오. 📏"
FAILED = "⚠️ 말투를 저장하지 못했소. 잠시 후 다시 시도하시오. 🔧"
READ_FAILED = "⚠️ 말투를 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"
SAVED = "💾✅ 말투를 저장했소. 🎭"
RESET = "↩️ 기본 말투로 돌아갔소. 🙆"
CLOSED = "👋 말투 화면을 닫았소."
_SHOWN = 1700


def tone_message(text: str | None) -> str:
    """Current tone shown as a quote; long text is cut for Discord, never stored cut."""
    label = "🎭 지금 적용 중인 말투: " + ("기본 말투" if text is None else "이 서버 말투")
    body = TONE_DEFAULT if text is None else text
    if len(body) > _SHOWN:
        body = body[:_SHOWN] + "…"
    quoted = "\n".join("> " + line if line else ">" for line in body.splitlines())
    return f"{label}\n{quoted}\n✏️ 수정하거나 기본값으로 되돌릴 수 있소. 👇"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ToneModal(discord.ui.Modal, title="말투·성격 수정"):
    def __init__(self, view: ToneView, current: str) -> None:
        super().__init__(timeout=300)
        self.view = view
        self.text: discord.ui.TextInput[ToneModal] = discord.ui.TextInput(
            label="말투·성격 (사실·금지선·형식 규칙은 바뀌지 않소)",
            style=discord.TextStyle.paragraph, default=current, max_length=TONE_LIMIT,
            required=True,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not await view.check(interaction):
            return
        try:
            content = clean_tone(str(self.text.value))
        except ToneTooLong:
            await reject(interaction, EMPTY)
            return
        await view.write(interaction, content)


class EditTone(discord.ui.Button["ToneView"]):
    def __init__(self) -> None:
        super().__init__(label="수정", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        # A modal must be the first response, so only cheap checks here; submit rechecks all.
        if not view.owned(interaction):
            await reject(interaction, DENIED)
            return
        if view.expired():
            await reject(interaction, EXPIRED)
            return
        await interaction.response.send_modal(ToneModal(view, view.text or TONE_DEFAULT))


class ResetTone(discord.ui.Button["ToneView"]):
    def __init__(self) -> None:
        super().__init__(label="기본값으로", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        if await view.check(interaction):
            await view.write(interaction, None)


class CloseTone(discord.ui.Button["ToneView"]):
    def __init__(self) -> None:
        super().__init__(label="닫기", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        if not view.owned(interaction):
            await reject(interaction, DENIED)
            return
        view.finish()
        await interaction.response.edit_message(content=CLOSED, view=view)


class ToneView(discord.ui.View):
    def __init__(
        self, tones: SQLiteToneStore, roles: ManagerRoleStore, guild_id: int, owner_id: int,
        *, snapshot: tuple[int, str | None],
    ) -> None:
        super().__init__(timeout=120)
        self.tones = tones
        self.roles = roles
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.version, self.text = snapshot
        self.expires_at = monotonic() + 120
        self.lock = asyncio.Lock()
        self.message: discord.Message | None = None
        for item in (EditTone(), ResetTone(), CloseTone()):
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
        """Opener, server, time limit and the 1.1.3 permission rule on every change."""
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

    async def write(self, interaction: discord.Interaction, content: str | None) -> None:
        async with self.lock:
            try:
                self.version = await asyncio.to_thread(
                    self.tones.save, self.guild_id, content, expected_version=self.version,
                )
            except ConcurrentUpdate:
                await reject(interaction, CHANGED)
                return
            except Exception:  # noqa: BLE001 - never echo the tone or the error
                LOGGER.warning("tone_save_failed")
                await reject(interaction, FAILED)
                return
        self.text = content
        if content is None:
            LOGGER.info("tone_reset at=%s", _now())
        else:
            LOGGER.info("tone_saved at=%s chars=%d", _now(), len(content))
        self.finish()
        notice = SAVED if content is not None else RESET
        await interaction.edit_original_response(content=f"{notice}\n{tone_message(content)}", view=self)

    async def on_timeout(self) -> None:
        self.finish()
        if self.message is not None:
            try:
                await self.message.edit(content=EXPIRED, view=self)
            except discord.HTTPException:
                LOGGER.warning("tone_view_expired_edit_failed")


def install_tone_command(
    tree: app_commands.CommandTree, tones: SQLiteToneStore, roles: ManagerRoleStore,
) -> None:
    @bot_command(roles)
    async def tone(interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None  # gated() answers outside servers
        try:
            snapshot = await asyncio.to_thread(tones.snapshot, guild.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("tone_read_failed")
            await reject(interaction, READ_FAILED)
            return
        view = ToneView(tones, roles, guild.id, interaction.user.id, snapshot=snapshot)
        await interaction.edit_original_response(content=tone_message(snapshot[1]), view=view)
        view.message = await interaction.original_response()

    tree.add_command(app_commands.Command(
        name="말투", description="요약봇의 말투·성격을 보고 고치오", callback=tone,
    ))
