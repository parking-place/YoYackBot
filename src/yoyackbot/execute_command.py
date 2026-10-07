"""`/처형 대상 시간 사유` (1.4.0): members with a 처형 role time someone out through the bot."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import timedelta

import discord
from discord import app_commands

from yoyackbot.execution import SQLiteExecutionStore
from yoyackbot.notices import localize

LOGGER = logging.getLogger(__name__)
DEFAULT_SECONDS = 30
DEFAULT_REASON = "내맴"
MAX_SECONDS = 28 * 24 * 3600  # Discord's timeout limit
MAX_REASON = 400
_UNITS = {"초": 1, "분": 60, "시간": 3600, "일": 86400}
_DURATION = re.compile(r"([0-9]{1,7})\s*(초|분|시간|일)?")

NOT_ALLOWED = "🚫 처형은 처형 역할이 있는 사람이나 관리자만 할 수 있소. 🙅"
BAD_TIME = "⏱️ 시간은 `30초`·`10분`·`2시간`·`1일`처럼 쓰시오(숫자만 쓰면 초, 최대 28일). 📏"
LONG_REASON = f"✂️ 사유는 {MAX_REASON}자까지만 쓰시오. 📏"
SELF = "🙃 자기 자신은 처형할 수 없소."
BOT_TARGET = "🤖 봇은 처형할 수 없소."
PROTECTED = "🛡️ 서버 주인이나 관리자는 처형할 수 없소."
HIGHER = "⬆️ 자기와 같거나 높은 역할의 사람은 처형할 수 없소."
BOT_CANNOT = "🔧 봇에 타임아웃 권한이 없거나 봇의 역할이 그 사람보다 낮아 처형할 수 없소."
FAILED = "⚠️ 처형하지 못했소. 잠시 후 다시 시도하시오. 🔧"
READ_FAILED = "⚠️ 처형 설정을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"


class DurationError(ValueError):
    """The time option is not a whole number of 초/분/시간/일 between 1 second and 28 days."""


def parse_duration(text: str | None) -> int:
    if text is None or not text.strip():
        return DEFAULT_SECONDS
    match = _DURATION.fullmatch(text.strip())
    if match is None:
        raise DurationError(text)
    seconds = int(match.group(1)) * _UNITS[match.group(2) or "초"]
    if not 1 <= seconds <= MAX_SECONDS:
        raise DurationError(text)
    return seconds


def clean_reason(text: str | None) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned or DEFAULT_REASON


def span_text(seconds: int) -> str:
    parts = []
    for unit, size in (("일", 86400), ("시간", 3600), ("분", 60), ("초", 1)):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return " ".join(parts)


def _position(member: object) -> int:
    return getattr(getattr(member, "top_role", None), "position", 0)


def refusal(guild: discord.Guild, caller: object, target: object) -> str | None:
    """Why this caller may not time out this target through the bot, or None."""
    owner_id = getattr(guild, "owner_id", None)
    if target.id == caller.id:
        return SELF
    if getattr(target, "bot", False):
        return BOT_TARGET
    target_permissions = getattr(target, "guild_permissions", None)
    if target.id == owner_id or getattr(target_permissions, "administrator", False):
        return PROTECTED
    if caller.id != owner_id and _position(target) >= _position(caller):
        return HIGHER
    me = getattr(guild, "me", None)
    my_permissions = getattr(me, "guild_permissions", None)
    if me is None or not getattr(my_permissions, "moderate_members", False) or _position(target) >= _position(me):
        return BOT_CANNOT
    return None


async def _answer(interaction: discord.Interaction, text: str) -> None:
    await interaction.followup.send(
        localize(interaction.guild_id, text), ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def run_execution(
    interaction: discord.Interaction, target: discord.Member, time_text: str | None,
    reason_text: str | None, *, store: SQLiteExecutionStore,
    remember: Callable[[int, int, int], None],
) -> str:
    """Returns an outcome category (logged without names or reason)."""
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    if guild is None:
        await _answer(interaction, NOT_ALLOWED)
        return "not_allowed"
    try:
        caller = await guild.fetch_member(interaction.user.id)
    except discord.HTTPException:
        await _answer(interaction, NOT_ALLOWED)
        return "not_allowed"
    try:
        roles = await asyncio.to_thread(store.roles, guild.id)
    except Exception:  # noqa: BLE001
        LOGGER.warning("execution_roles_unreadable")
        await _answer(interaction, READ_FAILED)
        return "unavailable"
    permissions = getattr(caller, "guild_permissions", None)
    if not (
        caller.id == getattr(guild, "owner_id", None) or getattr(permissions, "administrator", False)
        or any(getattr(role, "id", None) in roles for role in getattr(caller, "roles", ()))
    ):
        await _answer(interaction, NOT_ALLOWED)
        return "not_allowed"
    try:
        seconds = parse_duration(time_text)
    except DurationError:
        await _answer(interaction, BAD_TIME)
        return "bad_time"
    reason = clean_reason(reason_text)
    if len(reason) > MAX_REASON:
        await _answer(interaction, LONG_REASON)
        return "long_reason"
    blocked = refusal(guild, caller, target)
    if blocked is not None:
        await _answer(interaction, blocked)
        return "refused"
    remember(guild.id, target.id, caller.id)  # the audit entry will name the bot
    try:
        await target.timeout(timedelta(seconds=seconds), reason=reason)
    except discord.Forbidden:
        await _answer(interaction, BOT_CANNOT)
        return "forbidden"
    except discord.HTTPException:
        await _answer(interaction, FAILED)
        return "failed"
    await _answer(interaction, f"⚔️ <@{target.id}>을(를) {span_text(seconds)} 동안 처형했소. 📝 사유: {reason}")
    return "success"


def install_execute_command(
    tree: app_commands.CommandTree, store: SQLiteExecutionStore,
    remember: Callable[[int, int, int], None],
) -> None:
    @app_commands.guild_only()
    @app_commands.default_permissions(use_application_commands=True)
    @app_commands.describe(대상="처형할 사람", 시간="예: 30초, 10분, 2시간, 1일 (기본 30초)", 사유="기본: 내맴")
    async def execute(
        interaction: discord.Interaction, 대상: discord.Member,
        시간: str | None = None, 사유: str | None = None,
    ) -> None:
        outcome = await run_execution(interaction, 대상, 시간, 사유, store=store, remember=remember)
        LOGGER.info("execution_command outcome=%s", outcome)

    execute.__yoyack_gated__ = True  # type: ignore[attr-defined] - roles checked at run time
    tree.add_command(app_commands.Command(
        name="처형", description="처형 역할로 이 사람을 타임아웃하오", callback=execute,
    ))
