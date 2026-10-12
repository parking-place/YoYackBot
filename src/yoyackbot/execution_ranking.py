"""`/처형순위 [기간]` (1.4.2): today's, this week's or this month's 처형 ranking, for everyone."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from yoyackbot.execution import Ranking, SQLiteExecutionStore
from yoyackbot.notices import localize

LOGGER = logging.getLogger(__name__)
DEFAULT_ZONE = ZoneInfo("Asia/Seoul")
PERIODS = {"일간": "day", "주간": "week", "월간": "month"}
TITLES = {
    "day": "🏆 **오늘의 처형 순위**",
    "week": "🏆 **이번 주 처형 순위**",
    "month": "🏆 **이번 달 처형 순위**",
}
PEACEFUL = {
    "day": "🕊️ 오늘은 처형이 없었소. 평화로웠구려.",
    "week": "🕊️ 이번 주는 처형이 없었소. 평화로웠구려.",
    "month": "🕊️ 이번 달은 처형이 없었소. 평화로웠구려.",
}
VICTIMS = "☠️ **단골 시체**"
EXECUTIONERS = "🗡️ **처형 장인**"
NO_EXECUTIONER = "🤷 누가 처형했는지 확인된 기록이 없소."
READ_FAILED = "⚠️ 처형 기록을 읽지 못했소. 잠시 후 다시 시도하시오. 🔧"
MEDALS = ("🥇", "🥈", "🥉")


def period_start(period: str, now: datetime, zone: ZoneInfo | None = None) -> datetime:
    """Midnight today, Monday midnight this week or the 1st of this month, in the bot's zone."""
    local = now.astimezone(zone or DEFAULT_ZONE)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        midnight -= timedelta(days=midnight.weekday())
    elif period == "month":
        midnight = midnight.replace(day=1)
    return midnight


def dead_text(seconds: int) -> str:
    if seconds <= 0:
        return "0초"
    parts = []
    for unit, size in (("일", 86400), ("시간", 3600), ("분", 60), ("초", 1)):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return " ".join(parts[:2])


def _place(index: int) -> str:
    return MEDALS[index] if index < len(MEDALS) else f"{index + 1}."


def ranking_message(period: str, ranking: Ranking) -> str:
    if ranking.total == 0:
        return f"{TITLES[period]}\n\n{PEACEFUL[period]}"
    lines = [TITLES[period], "", VICTIMS]
    lines += [f"{_place(i)} <@{member}> — {times}회, ⏳{dead_text(dead)}"
              for i, (member, times, dead) in enumerate(ranking.victims)]
    lines += ["", EXECUTIONERS]
    lines += [f"{_place(i)} <@{member}> — {times}회" for i, (member, times) in enumerate(ranking.executioners)]
    if not ranking.executioners:
        lines.append(NO_EXECUTIONER)
    lines += ["", f"⚔️ 이 기간 처형은 모두 {ranking.total}건이오."]
    return "\n".join(lines)


def install_ranking_command(
    tree: app_commands.CommandTree, store: SQLiteExecutionStore,
    zone: ZoneInfo | None = None, clock: Callable[[], datetime] | None = None,
) -> None:
    # Like `/도움말`: every member may ask, but the answer is for everyone (user decision).
    @app_commands.guild_only()
    @app_commands.describe(기간="일간(오늘)·주간(이번 주)·월간(이번 달), 기본 일간")
    @app_commands.choices(기간=[app_commands.Choice(name=name, value=name) for name in PERIODS])
    async def ranking(interaction: discord.Interaction, 기간: str = "일간") -> None:
        period = PERIODS.get(기간, "day")
        now = (clock or (lambda: datetime.now(UTC)))()
        guild_id = interaction.guild_id
        try:
            result = await asyncio.to_thread(
                store.ranking, guild_id, period_start(period, now, zone), now + timedelta(seconds=1),
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("execution_ranking_unreadable")
            await interaction.response.send_message(localize(guild_id, READ_FAILED), ephemeral=True)
            return
        await interaction.response.send_message(
            localize(guild_id, ranking_message(period, result)),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        LOGGER.info("execution_ranking period=%s total=%d", period, result.total)

    tree.add_command(app_commands.Command(
        name="처형순위", description="오늘·이번 주·이번 달의 처형 순위를 모두에게 보여 주오",
        callback=ranking,
    ))
