"""`/말투`: see and change this server's tone and personality (1.3.0); 1.4.2 picks a preset or,
for 사용자정의 only, edits it."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic

import discord
from discord import app_commands

from yoyackbot.channel_config import ConcurrentUpdate, allowed, bot_command, reject
from yoyackbot.manager_roles import ManagerRoleStore
from yoyackbot.notices import localize
from yoyackbot.summary_prompt import TONE_DEFAULT, TONE_LIMIT
from yoyackbot.tone import SQLiteToneStore, ToneTooLong, clean_tone
from yoyackbot.tone_presets import PRESETS, find_preset

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
NOTICES_WRITING = "📝 이 서버의 안내 문구를 새 말투로 고쳐 쓰는 중이오. 끝나면 알려주겠소. ⏳"
NOTICES_FAILED = (
    "⚠️ 안내 문구를 새 말투로 바꾸지 못해 기본 문구를 쓰오. 말투를 다시 저장하면 다시 해보겠소. 🔧"
)
_SHOWN = 1700
# 1.4.0: told about every saved change (interaction, server, tone version, tone or None), so the
# server's notices are rewritten for the new tone or dropped on reset.
ToneChanged = Callable[[discord.Interaction, int, int, str | None], None]


DEFAULT_CHOICE = "default"
CUSTOM_CHOICE = "custom"


def current_choice(text: str | None) -> str:
    if text is None:
        return DEFAULT_CHOICE
    preset = find_preset(text)
    return preset.key if preset is not None else CUSTOM_CHOICE


def tone_message(text: str | None) -> str:
    """Current tone shown as a quote; long text is cut for Discord, never stored cut."""
    preset = find_preset(text)
    label = (
        "🎭 지금 적용 중인 말투: 기본 말투" if text is None
        else f"🎭 지금 적용 중인 말투: {preset.name} 프리셋" if preset is not None
        else "🎭 지금 적용 중인 말투: 이 서버 말투"
    )
    body = TONE_DEFAULT if text is None else text
    if len(body) > _SHOWN:
        body = body[:_SHOWN] + "…"
    quoted = "\n".join("> " + line if line else ">" for line in body.splitlines())
    return f"{label}\n{quoted}\n✏️ 아래에서 프리셋을 고르시오. 직접 고치려면 사용자정의를 고르시오. 👇"


def notices_report(written: int, kept: int) -> str:
    """What the opener of `/말투` is told once the notices are rewritten (1.4.0)."""
    if written == 0:
        return NOTICES_FAILED
    if kept:
        return f"🎭 안내 문구 {written}개를 바꾸었고, 바꾸지 못한 {kept}개는 기본 문구를 쓰오. 🔧"
    return f"🎭✅ 안내 문구 {written}개를 이 서버 말투로 바꾸었소. 🎉"


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


class PresetSelect(discord.ui.Select["ToneView"]):
    """기본, the presets and 사용자정의; only 사용자정의 opens the editor (1.4.2 user decision)."""

    def __init__(self, current: str) -> None:
        choices = [(DEFAULT_CHOICE, "기본", "📜 지금까지의 하오체 말투")]
        choices += [(preset.key, preset.name, "🎭 안내 문구까지 정해 둔 프리셋") for preset in PRESETS]
        choices += [(CUSTOM_CHOICE, "사용자정의", "✏️ 말투를 직접 고치오")]
        super().__init__(
            placeholder="🎭 말투 프리셋을 고르시오",
            options=[discord.SelectOption(label=label, value=value, description=about,
                                          default=value == current)
                     for value, label, about in choices],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        assert view is not None
        choice = self.values[0]
        if choice == CUSTOM_CHOICE:
            # A modal must be the first response, so only cheap checks here; submit rechecks all.
            if not view.owned(interaction):
                await reject(interaction, DENIED)
                return
            if view.expired():
                await reject(interaction, EXPIRED)
                return
            await interaction.response.send_modal(ToneModal(view, view.text or TONE_DEFAULT))
            return
        if await view.check(interaction):
            preset = next((item for item in PRESETS if item.key == choice), None)
            await view.write(interaction, None if preset is None else preset.tone)


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
        await interaction.response.edit_message(content=localize(interaction.guild_id, CLOSED), view=view)


class ToneView(discord.ui.View):
    def __init__(
        self, tones: SQLiteToneStore, roles: ManagerRoleStore, guild_id: int, owner_id: int,
        *, snapshot: tuple[int, str | None], on_change: ToneChanged | None = None,
    ) -> None:
        super().__init__(timeout=120)
        self.on_change = on_change
        self.tones = tones
        self.roles = roles
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.version, self.text = snapshot
        self.expires_at = monotonic() + 120
        self.lock = asyncio.Lock()
        self.message: discord.Message | None = None
        for item in (PresetSelect(current_choice(self.text)), CloseTone()):
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
        elif (chosen := find_preset(content)) is not None:
            LOGGER.info("tone_preset at=%s preset=%s", _now(), chosen.key)
        else:
            LOGGER.info("tone_saved at=%s chars=%d", _now(), len(content))
        self.finish()
        preset = find_preset(content)
        notice = (
            RESET if content is None
            else f"💾✅ 말투를 {preset.name} 프리셋으로 바꾸었소. 🎭" if preset is not None
            else SAVED
        )
        if self.on_change is not None:  # first, so this reply already drops the old notices
            self.on_change(interaction, self.guild_id, self.version, content)
            if content is not None and preset is None:  # a preset brings its notices with it
                notice += "\n" + NOTICES_WRITING
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, f"{notice}\n{tone_message(content)}"), view=self,
        )

    async def on_timeout(self) -> None:
        self.finish()
        if self.message is not None:
            try:
                await self.message.edit(content=localize(self.guild_id, EXPIRED), view=self)
            except discord.HTTPException:
                LOGGER.warning("tone_view_expired_edit_failed")


def install_tone_command(
    tree: app_commands.CommandTree, tones: SQLiteToneStore, roles: ManagerRoleStore,
    on_change: ToneChanged | None = None,
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
        view = ToneView(
            tones, roles, guild.id, interaction.user.id, snapshot=snapshot, on_change=on_change,
        )
        await interaction.edit_original_response(
            content=localize(interaction.guild_id, tone_message(snapshot[1])), view=view,
        )
        view.message = await interaction.original_response()

    tree.add_command(app_commands.Command(
        name="말투", description="요약봇의 말투·성격을 보고 고치오", callback=tone,
    ))
