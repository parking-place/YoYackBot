"""List this Guild's watched text channels that the requester can see, in Discord order."""

import asyncio
import logging
import re
from collections.abc import Iterable
from typing import Any

import discord

from yoyackbot.channel_config import WatchStore

LOGGER = logging.getLogger(__name__)
LIST_HEADER = "📡👀 지금 본인이 보고 있는 채널을 알려주겠소"
LIST_FOOTER = "✅ 이상이오. 🫡"
EMPTY_NOTICE = "🫥 지금 보고 있는 채널이 없소. `/채널 설정`으로 정하시오. 🛠️"
DM_DELIVERED_NOTICE = "📨 목록을 개인 메시지로 전달했소."
DM_FAILED_NOTICE = "📭 목록을 개인 메시지로 전달하지 못했소. DM 수신 설정을 확인하시오."
DEFAULT_LIMIT = 1900
_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]])")


def escape_name(name: str) -> str:
    """Show a channel name literally; mentions are already disabled on every send."""
    return _MARKDOWN.sub(r"\\\1", name)


def _order(channel: discord.TextChannel) -> tuple[int, int, int]:
    category = getattr(channel, "category", None)
    return (-1 if category is None else category.position, channel.position, channel.id)


def visible_watched_channels(
    guild: discord.Guild, watched_ids: Iterable[int], requester: Any,
) -> list[discord.TextChannel]:
    """Skip channels that vanished, are not text channels, or the requester cannot view."""
    channels = []
    for channel_id in watched_ids:
        channel = guild.get_channel(channel_id)
        if getattr(channel, "type", None) is not discord.ChannelType.text:
            continue
        try:
            if not channel.permissions_for(requester).view_channel:
                continue
        except (AttributeError, TypeError):
            continue
        channels.append(channel)
    return sorted(channels, key=_order)


def channel_list_messages(names: list[str], *, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Split only between whole lines; the header opens the first part and the footer ends the last."""
    if not names:
        return [EMPTY_NOTICE]
    lines = [LIST_HEADER, *(f" - 💬 {escape_name(name)}" for name in names),
             LIST_FOOTER]
    parts: list[str] = []
    current = ""
    for line in lines:
        line = line[:limit]
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    parts.append(current)
    return parts


async def deliver_channel_list(
    guild: discord.Guild,
    requester: Any,
    store: WatchStore,
    *,
    origin_channel_id: int,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """Deliver privately, checking the current member and selection before every part.

    Only a fixed, non-sensitive acknowledgement crosses the public-channel boundary.
    A changed selection stops delivery instead of risking stale names in later parts.
    Discord membership and permissions cannot be atomically locked with a DM send;
    REST membership and cached channel/role permissions are checked for each part.
    """
    expected: tuple[int, tuple[tuple[int, str], ...]] | None = None
    parts: list[str] = []
    part_index = 0
    try:
        if getattr(getattr(requester, "guild", None), "id", None) != guild.id:
            raise ValueError("requester guild mismatch")
        while True:
            # Do not rely on the author object captured when the command arrived:
            # that object can survive role removal or the member leaving the Guild.
            member = await guild.fetch_member(requester.id)
            if member.id != requester.id or member.guild.id != guild.id:
                raise ValueError("current member mismatch")
            version, watched = await asyncio.to_thread(store.snapshot, guild.id)
            origin = guild.get_channel(origin_channel_id)
            if (
                origin_channel_id not in watched
                or getattr(origin, "type", None) is not discord.ChannelType.text
                or not origin.permissions_for(member).view_channel
            ):
                raise ValueError("request channel no longer available")
            channels = visible_watched_channels(guild, watched, member)
            current = (version, tuple((channel.id, channel.name) for channel in channels))
            if expected is None:
                expected = current
                parts = channel_list_messages([channel.name for channel in channels], limit=limit)
            elif current != expected:
                raise ValueError("channel selection changed")
            await member.send(
                parts[part_index],
                allowed_mentions=discord.AllowedMentions.none(),
                suppress_embeds=True,
            )
            part_index += 1
            if part_index == len(parts):
                LOGGER.info("channel_list_delivery outcome=ok")
                return DM_DELIVERED_NOTICE
    except Exception:  # noqa: BLE001 - no permission/transport detail crosses the public boundary
        LOGGER.warning("channel_list_delivery outcome=unavailable")
        return DM_FAILED_NOTICE
