"""Bounded Discord History paging for one frozen Guild/channel time window."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from itertools import pairwise
from typing import Protocol

import discord
from aiohttp import ClientError

from yoyackbot.domain import MessageRecord
from yoyackbot.reply_refs import reply_target


class HistoryFailure(Enum):
    PERMISSION = "permission"
    CHANNEL_GONE = "channel_gone"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    TIMEOUT = "timeout"
    PAGE_LIMIT = "page_limit"
    CHANNEL_MISMATCH = "channel_mismatch"
    INVALID_PAGE = "invalid_page"
    SIZE_LIMIT = "size_limit"


class HistoryError(RuntimeError):
    def __init__(self, kind: HistoryFailure) -> None:
        super().__init__(f"History collection stopped: {kind.value}")
        self.kind = kind


class HistoryPageSource(Protocol):
    async def fetch_page(
        self, channel: discord.TextChannel, *, before: int, limit: int, after: int | None = None,
    ) -> Sequence[discord.Message]: ...


class DiscordHistorySource:
    async def fetch_page(
        self, channel: discord.TextChannel, *, before: int, limit: int, after: int | None = None,
    ) -> Sequence[discord.Message]:
        return [
            message
            async for message in channel.history(
                limit=limit, before=discord.Object(id=before),
                after=discord.Object(id=after) if after is not None else None, oldest_first=False,
            )
        ]


@dataclass(frozen=True)
class HistoryResult:
    messages: tuple[MessageRecord, ...]
    pages: int
    exhausted: bool = True


def _failure(error: Exception) -> HistoryFailure:
    if isinstance(error, discord.Forbidden):
        return HistoryFailure.PERMISSION
    if isinstance(error, discord.NotFound):
        return HistoryFailure.CHANNEL_GONE
    if isinstance(error, discord.HTTPException) and error.status == 429:
        return HistoryFailure.RATE_LIMIT
    return HistoryFailure.NETWORK


class HistoryAdapter:
    def __init__(
        self,
        source: HistoryPageSource | None = None,
        *,
        page_size: int = 100,
        max_pages: int = 100,
        timeout_seconds: float = 30,
        retries: int = 2,
        max_records: int = 10_000,
        max_content_bytes: int = 4_000_000,
    ) -> None:
        if (
            not 1 <= page_size <= 100
            or max_pages < 1
            or timeout_seconds <= 0
            or retries < 0
            or max_records < 1
            or max_content_bytes < 1
        ):
            raise ValueError("History limits must be positive and bounded")
        self.source = source or DiscordHistorySource()
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.max_records = max_records
        self.max_content_bytes = max_content_bytes

    async def _page(
        self, channel: discord.TextChannel, before: int,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> Sequence[discord.Message]:
        for attempt in range(self.retries + 1):
            if can_continue is not None and not await can_continue():
                raise HistoryError(HistoryFailure.PERMISSION)
            try:
                return await self.source.fetch_page(channel, before=before, limit=self.page_size)
            except (discord.HTTPException, ClientError, OSError) as exc:
                kind = _failure(exc)
                if kind in {HistoryFailure.PERMISSION, HistoryFailure.CHANNEL_GONE}:
                    raise HistoryError(kind) from exc
                if attempt >= self.retries:
                    raise HistoryError(kind) from exc
                await asyncio.sleep(min(0.2 * (2**attempt), 1.0))
        raise AssertionError("History retry loop must return or raise")

    async def collect(
        self,
        channel: discord.TextChannel,
        *,
        guild_id: int,
        channel_id: int,
        start: datetime,
        end: datetime,
        trigger_message_id: int | None = None,
        limit_messages: int | None = None,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> HistoryResult:
        """Return oldest-first records; count-limited results never claim full coverage."""
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("History range must be a nonempty aware interval")
        if limit_messages is not None and limit_messages < 1:
            raise ValueError("limit_messages must be positive")
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
        ):
            raise HistoryError(HistoryFailure.CHANNEL_MISMATCH)
        before = discord.utils.time_snowflake(end, high=True) + 1
        records: dict[int, MessageRecord] = {}
        content_bytes = 0
        pages = 0
        try:
            async with asyncio.timeout(self.timeout_seconds):
                while pages < self.max_pages:
                    page = await self._page(channel, before, can_continue)
                    pages += 1
                    if not page:
                        return HistoryResult(tuple(sorted(records.values(), key=_sort_key)), pages)
                    if any(
                        message.id >= before
                        or getattr(message.channel, "id", None) != channel_id
                        or getattr(getattr(message, "guild", None), "id", None) != guild_id
                        for message in page
                    ) or any(left.id <= right.id for left, right in pairwise(page)):
                        raise HistoryError(HistoryFailure.INVALID_PAGE)
                    oldest = min(message.id for message in page)
                    for message in page:
                        if not start <= message.created_at < end or message.id == trigger_message_id:
                            continue
                        if (
                            message.webhook_id is not None
                            or message.author.bot
                            or message.type not in {discord.MessageType.default, discord.MessageType.reply}
                        ):
                            continue
                        record = MessageRecord(
                            message_id=message.id,
                            guild_id=guild_id,
                            channel_id=channel_id,
                            author_id=message.author.id,
                            author_name=getattr(message.author, "display_name", None)
                            or getattr(message.author, "name", "unknown"),
                            content=message.content,
                            created_at=message.created_at,
                            edited_at=message.edited_at,
                            has_attachment=bool(getattr(message, "attachments", ())),
                            is_reply=message.type is discord.MessageType.reply,
                            reply_to_message_id=reply_target(message, guild_id, channel_id),
                        )
                        previous = records.get(message.id)
                        if previous is not None:
                            content_bytes -= len(previous.content.encode("utf-8"))
                        content_bytes += len(record.content.encode("utf-8"))
                        records[message.id] = record
                        if len(records) > self.max_records or content_bytes > self.max_content_bytes:
                            raise HistoryError(HistoryFailure.SIZE_LIMIT)
                        if limit_messages is not None and len(records) >= limit_messages:
                            return HistoryResult(
                                tuple(sorted(records.values(), key=_sort_key)), pages, exhausted=False
                            )
                    if len(page) < self.page_size or any(message.created_at < start for message in page):
                        return HistoryResult(tuple(sorted(records.values(), key=_sort_key)), pages)
                    if oldest >= before:
                        raise HistoryError(HistoryFailure.INVALID_PAGE)
                    before = oldest
        except TimeoutError as exc:
            raise HistoryError(HistoryFailure.TIMEOUT) from exc
        raise HistoryError(HistoryFailure.PAGE_LIMIT)


def _sort_key(record: MessageRecord) -> tuple[datetime, int]:
    return record.created_at, record.message_id
