"""Fail-closed collection routing with a settings-verified cache fallback."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import discord

from yoyackbot.count_collection import CountCollector, CountError, CountFailure
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind
from yoyackbot.history import HistoryAdapter
from yoyackbot.long_range import LongRangeCollector, LongRangeError, LongRangeFailure
from yoyackbot.message_store import MessageStoreError
from yoyackbot.range_collection import CollectionError, CollectionFailure
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError


class CollectionUnavailable(RuntimeError):
    """Watched-channel settings cannot be trusted for this request."""


EMPTY_NOTICE = "해당 범위에 요약할 일반 사용자 대화가 없소."


@dataclass(frozen=True)
class CollectionOutcome:
    messages: tuple[MessageRecord, ...]
    shortage: int
    searched_since: datetime
    pages: int
    fallback_used: bool
    cache_count: int = 0
    history_count: int = 0

    @property
    def empty(self) -> bool:
        return not self.messages

    @property
    def requires_model(self) -> bool:
        return bool(self.messages)

    @property
    def empty_notice(self) -> str | None:
        return EMPTY_NOTICE if self.empty else None


class CollectionCoordinator:
    def __init__(
        self,
        watches: SQLiteWatchStore,
        time: LongRangeCollector,
        count: CountCollector,
        history: HistoryAdapter,
        *,
        max_days: int = 30,
        max_count: int = 1000,
        max_content_bytes: int = 1_000_000,
        max_pages: int = 100,
    ) -> None:
        if min(max_days, max_count, max_content_bytes, max_pages) < 1:
            raise ValueError("Collection limits must be positive")
        self.watches = watches
        self.time = time
        self.count = count
        self.history = history
        self.max_days = max_days
        self.max_count = max_count
        self.max_content_bytes = max_content_bytes
        self.max_pages = max_pages

    async def collect(
        self,
        channel: discord.TextChannel,
        *,
        guild_id: int,
        channel_id: int,
        request: RangeRequest,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> CollectionOutcome:
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
        ):
            raise CollectionError(CollectionFailure.CHANNEL_MISMATCH)
        version = await self._trusted_version(guild_id, channel_id)
        try:
            if request.kind is RequestKind.TIME:
                assert request.start is not None
                result = await self.time.collect(
                    channel,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    start=request.start,
                    end=request.accepted_at,
                    accepted_at=request.accepted_at,
                    trigger_message_id=request.trigger_message_id,
                    can_continue=can_continue,
                )
                fetched = result.history_count
                outcome = CollectionOutcome(
                    result.messages, 0, request.start, result.pages, False,
                    len(result.messages) - fetched, fetched,
                )
            else:
                assert request.count is not None
                result = await self.count.collect(
                    channel,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    count=request.count,
                    accepted_at=request.accepted_at,
                    trigger_message_id=request.trigger_message_id,
                    can_continue=can_continue,
                )
                outcome = CollectionOutcome(
                    result.messages, result.shortage, result.searched_since, result.pages, False,
                    len(result.messages) - result.history_count, result.history_count,
                )
        except MessageStoreError:
            if await self._trusted_version(guild_id, channel_id) != version:
                raise CollectionUnavailable("Channel settings changed during cache failure") from None
            outcome = await self._direct(
                channel, guild_id, channel_id, request, can_continue=can_continue
            )
        except WatchStoreError as exc:
            raise CollectionUnavailable("Channel settings are unavailable") from exc
        if await self._trusted_version(guild_id, channel_id) != version:
            raise CollectionUnavailable("Channel settings changed during collection")
        return outcome

    async def _trusted_version(self, guild_id: int, channel_id: int) -> int:
        try:
            version, selected = await asyncio.to_thread(self.watches.snapshot, guild_id)
        except WatchStoreError as exc:
            raise CollectionUnavailable("Channel settings are unavailable") from exc
        if channel_id not in selected:
            raise CollectionError(CollectionFailure.UNWATCHED)
        return version

    async def _direct(
        self, channel: discord.TextChannel, guild_id: int, channel_id: int, request: RangeRequest,
        *, can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> CollectionOutcome:
        floor = request.accepted_at - timedelta(days=self.max_days)
        if request.kind is RequestKind.TIME:
            assert request.start is not None
            if request.start < floor:
                raise LongRangeError(LongRangeFailure.TOO_OLD)
            history = await self.history.collect(
                channel, guild_id=guild_id, channel_id=channel_id,
                start=request.start, end=request.accepted_at,
                trigger_message_id=request.trigger_message_id,
                can_continue=can_continue,
            )
            if not history.exhausted:
                raise CollectionError(CollectionFailure.INCOMPLETE)
            messages = history.messages
            shortage = 0
            searched_since = request.start
        else:
            assert request.count is not None
            if request.count > self.max_count:
                raise CountError(CountFailure.INVALID_COUNT)
            history = await self.history.collect(
                channel, guild_id=guild_id, channel_id=channel_id,
                start=floor, end=request.accepted_at,
                trigger_message_id=request.trigger_message_id,
                limit_messages=request.count,
                can_continue=can_continue,
            )
            messages = history.messages
            shortage = request.count - len(messages)
            searched_since = floor if shortage else messages[0].created_at
        if history.pages > self.max_pages:
            raise LongRangeError(LongRangeFailure.PAGE_LIMIT)
        if sum(len(item.content.encode("utf-8")) for item in messages) > self.max_content_bytes:
            raise LongRangeError(LongRangeFailure.INPUT_LIMIT)
        return CollectionOutcome(
            tuple(messages), shortage, searched_since, history.pages, True,
            0, len(messages),
        )
