"""Bounded Discord History paging for one frozen Guild/channel time window."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

import discord
from aiohttp import ClientError

from yoyackbot.domain import MessageRecord


class HistoryFailure(Enum):
    PERMISSION = "permission"
    CHANNEL_GONE = "channel_gone"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    TIMEOUT = "timeout"
    PAGE_LIMIT = "page_limit"
    CHANNEL_MISMATCH = "channel_mismatch"
    INVALID_PAGE = "invalid_page"


class HistoryError(RuntimeError):
    def __init__(self, kind: HistoryFailure) -> None:
        super().__init__(f"History collection stopped: {kind.value}")
        self.kind = kind


class HistoryPageSource(Protocol):
    async def fetch_page(
        self, channel: discord.TextChannel, *, before: int, limit: int
    ) -> Sequence[discord.Message]: ...


class DiscordHistorySource:
    async def fetch_page(
        self, channel: discord.TextChannel, *, before: int, limit: int
    ) -> Sequence[discord.Message]:
        return [
            message
            async for message in channel.history(
                limit=limit, before=discord.Object(id=before), oldest_first=False
            )
        ]


@dataclass(frozen=True)
class HistoryResult:
    messages: tuple[MessageRecord, ...]
    pages: int


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
    ) -> None:
        if not 1 <= page_size <= 100 or max_pages < 1 or timeout_seconds <= 0 or retries < 0:
            raise ValueError("History limits must be positive and bounded")
        self.source = source or DiscordHistorySource()
        self.page_size = page_size
        self.max_pages = max_pages
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    async def _page(self, channel: discord.TextChannel, before: int) -> Sequence[discord.Message]:
        for attempt in range(self.retries + 1):
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
    ) -> HistoryResult:
        """Return a complete oldest-first result or raise without a completion signal."""
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("History range must be a nonempty aware interval")
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
        ):
            raise HistoryError(HistoryFailure.CHANNEL_MISMATCH)
        before = discord.utils.time_snowflake(end, high=True) + 1
        records: dict[int, MessageRecord] = {}
        pages = 0
        try:
            async with asyncio.timeout(self.timeout_seconds):
                while pages < self.max_pages:
                    page = await self._page(channel, before)
                    pages += 1
                    if not page:
                        return HistoryResult(tuple(sorted(records.values(), key=_sort_key)), pages)
                    if any(
                        message.id >= before
                        or getattr(message.channel, "id", None) != channel_id
                        or getattr(getattr(message, "guild", None), "id", None) != guild_id
                        for message in page
                    ) or any(left.id <= right.id for left, right in zip(page, page[1:])):
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
                        records[message.id] = MessageRecord(
                            message_id=message.id,
                            guild_id=guild_id,
                            channel_id=channel_id,
                            author_id=message.author.id,
                            author_name=getattr(message.author, "display_name", None)
                            or getattr(message.author, "name", "unknown"),
                            content=message.content,
                            created_at=message.created_at,
                            edited_at=message.edited_at,
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
