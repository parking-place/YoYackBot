"""List this Guild's watched text channels that the requester can see, in Discord order."""

import re
from collections.abc import Iterable
from typing import Any

import discord

LIST_HEADER = "📡👀 지금 본인이 보고 있는 채널을 알려주겠소"
LIST_FOOTER = "✅ 이상이오. 🫡"
EMPTY_NOTICE = "🫥 지금 보고 있는 채널이 없소. `/채널 설정`으로 정하시오. 🛠️"
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
