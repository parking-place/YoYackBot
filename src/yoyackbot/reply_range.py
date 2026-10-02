"""1.3.0: `!!요약좀` sent as a reply summarizes from the replied-to message until now."""

import asyncio
from datetime import datetime, timedelta

import discord
from aiohttp import ClientError

from yoyackbot.config import Settings
from yoyackbot.domain import RangeRequest, RequestKind
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.parser import OptionKind
from yoyackbot.scope import RangeScope

OTHER_CHANNEL_NOTICE = "↩️ 같은 채널의 메시지에 답장해야 그 메시지부터 요약하오. 🙅"
MISSING_NOTICE = "🔍 답장한 메시지를 찾을 수 없소. 지워졌는지 확인하시오. 🗑️"
LOOKUP_FAILED_NOTICE = "⚠️ 답장한 메시지를 확인하지 못했소. 잠시 후 다시 시도하시오. 🔁"


def too_old_notice(days: int) -> str:
    return f"📅 답장한 메시지가 너무 오래됐소. 최근 {days}일 안의 메시지에 답장하시오. ⏳"


def too_many_notice(limit: int) -> str:
    return f"📚 답장한 메시지부터 대화가 {limit}개를 넘소. 더 가까운 메시지에 답장하시오. ✂️"


class ReplyRangeRefused(ValueError):
    """A fixed notice explains why this reply cannot set the range."""


def reply_reference(message: object) -> object | None:
    """The command's reply reference, or None for an ordinary command."""
    if getattr(message, "type", None) is not discord.MessageType.reply:
        return None
    reference = getattr(message, "reference", None)
    return reference if getattr(reference, "message_id", None) is not None else None


async def resolve_reply_range(
    message: discord.Message, reference: object, *, store: SQLiteMessageStore | None,
    settings: Settings, accepted_at: datetime, ignored_range: bool,
) -> tuple[RangeRequest, RangeScope]:
    """Find the target in the cache, else ask Discord once; check the age and count limits."""
    assert message.guild is not None
    guild_id, channel_id = message.guild.id, message.channel.id
    target_id = getattr(reference, "message_id", None)
    if (
        type(target_id) is not int or getattr(reference, "channel_id", None) != channel_id
        or getattr(reference, "guild_id", None) not in (None, guild_id)
    ):
        raise ReplyRangeRefused(OTHER_CHANNEL_NOTICE)
    created = None
    if store is not None:
        created = await asyncio.to_thread(store.created_at, guild_id, channel_id, target_id)
    if created is None:
        try:
            target = await message.channel.fetch_message(target_id)
        except discord.NotFound as exc:
            raise ReplyRangeRefused(MISSING_NOTICE) from exc
        except (discord.HTTPException, ClientError, OSError) as exc:
            raise ReplyRangeRefused(LOOKUP_FAILED_NOTICE) from exc
        if getattr(getattr(target, "channel", None), "id", None) != channel_id:
            raise ReplyRangeRefused(OTHER_CHANNEL_NOTICE)
        created = target.created_at
    days = min(settings.max_days, settings.cache_retention_days)
    if created < accepted_at - timedelta(days=days):
        raise ReplyRangeRefused(too_old_notice(days))
    start = min(created, accepted_at)
    if store is not None and await asyncio.to_thread(
        store.count_between, guild_id, channel_id, start, accepted_at,
        exclude_id=getattr(message, "id", None),
    ) > settings.max_messages:
        raise ReplyRangeRefused(too_many_notice(settings.max_messages))
    request = RangeRequest(
        RequestKind.TIME, accepted_at, start=start,
        trigger_message_id=getattr(message, "id", None), anchor_message_id=target_id,
    )
    return request, RangeScope(OptionKind.REPLY, ignored_range=ignored_range)
