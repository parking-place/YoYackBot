"""Select the latest verified human messages, supplementing gaps when needed."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

import discord

from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.history import HistoryAdapter
from yoyackbot.range_collection import CollectionError, CollectionFailure, TimeRangeCollector


class CountFailure(Enum):
    INVALID_COUNT = "invalid_count"
    INPUT_LIMIT = "input_limit"
    PAGE_LIMIT = "page_limit"


class CountError(RuntimeError):
    def __init__(self, kind: CountFailure) -> None:
        super().__init__(f"Count collection stopped: {kind.value}")
        self.kind = kind


@dataclass(frozen=True)
class CountResult:
    messages: tuple[MessageRecord, ...]
    requested: int
    shortage: int
    pages: int
    searched_since: datetime
    history_count: int = 0


class CountCollector:
    def __init__(
        self,
        recent: TimeRangeCollector,
        history: HistoryAdapter,
        *,
        retention_days: int = 7,
        max_days: int = 28,
        max_count: int = 1000,
        max_content_bytes: int = 1_000_000,
        max_pages: int = 100,
    ) -> None:
        if not 1 <= retention_days <= 30 or not 1 <= max_days <= 30:
            raise ValueError("Invalid collection window")
        if min(max_count, max_content_bytes, max_pages) < 1:
            raise ValueError("Collection budgets must be positive")
        self.recent = recent
        self.history = history
        self.retention_days = retention_days
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
        count: int,
        accepted_at: datetime,
        trigger_message_id: int | None = None,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> CountResult:
        if accepted_at.tzinfo is None or not 1 <= count <= self.max_count:
            raise CountError(CountFailure.INVALID_COUNT)
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
        ):
            raise CollectionError(CollectionFailure.CHANNEL_MISMATCH)
        version, selected = await asyncio.to_thread(self.recent.watches.snapshot, guild_id)
        if channel_id not in selected:
            raise CollectionError(CollectionFailure.UNWATCHED)
        cutoff = accepted_at - timedelta(days=self.retention_days)
        floor = accepted_at - timedelta(days=self.max_days)
        await asyncio.to_thread(self.recent.store.prune_before, cutoff)
        cached = await self._latest(guild_id, channel_id, cutoff, accepted_at, count,
                                    trigger_message_id)
        pages = 0
        history_ids: set[int] = set()
        if len(cached) >= count:
            candidate_start = cached[-1].created_at
            gaps = await asyncio.to_thread(
                self.recent.store.missing,
                guild_id,
                self._interval(channel_id, candidate_start, accepted_at),
            )
            if not gaps:
                return await self._finish(cached, count, pages, candidate_start,
                                          guild_id, channel_id, version)
            verified = await self.recent.collect(
                channel, guild_id=guild_id, channel_id=channel_id,
                start=candidate_start, end=accepted_at,
                trigger_message_id=trigger_message_id,
                can_continue=can_continue,
            )
            pages += verified.pages
            history_ids.update(verified.history_ids)
            self._check_pages(pages)
            cached = await self._latest(guild_id, channel_id, cutoff, accepted_at, count,
                                        trigger_message_id)
            if len(cached) >= count:
                new_start = cached[-1].created_at
                new_gaps = await asyncio.to_thread(
                    self.recent.store.missing,
                    guild_id,
                    CoverageInterval(channel_id, new_start, accepted_at),
                )
                if not new_gaps:
                    return await self._finish(cached, count, pages, new_start,
                                              guild_id, channel_id, version, history_ids)

        verified = await self.recent.collect(
            channel, guild_id=guild_id, channel_id=channel_id,
            start=cutoff, end=accepted_at, trigger_message_id=trigger_message_id,
            can_continue=can_continue,
        )
        pages += verified.pages
        history_ids.update(verified.history_ids)
        self._check_pages(pages)
        cached = await self._latest(guild_id, channel_id, cutoff, accepted_at, count,
                                    trigger_message_id)
        if len(cached) >= count:
            return await self._finish(cached, count, pages, cutoff, guild_id, channel_id,
                                      version, history_ids)

        older: list[MessageRecord] = []
        cursor = cutoff
        while cursor > floor and len(cached) + len(older) < count:
            if pages >= self.max_pages:
                raise CountError(CountFailure.PAGE_LIMIT)
            start = max(floor, cursor - timedelta(days=7))
            history = await self.history.collect(
                channel, guild_id=guild_id, channel_id=channel_id,
                start=start, end=cursor, trigger_message_id=trigger_message_id,
                limit_messages=count - len(cached) - len(older),
                can_continue=can_continue,
            )
            older.extend(history.messages)
            history_ids.update(item.message_id for item in history.messages)
            pages += history.pages
            self._check_pages(pages)
            cursor = start
        return await self._finish(
            [*cached, *older], count, pages, cursor, guild_id, channel_id, version, history_ids
        )

    async def _latest(self, guild_id, channel_id, start, end, count, excluded):
        return await asyncio.to_thread(
            self.recent.store.latest, guild_id, channel_id, start, end, count,
            exclude_id=excluded,
        )

    @staticmethod
    def _interval(channel_id, start, end):
        return CoverageInterval(channel_id, start, end)

    def _check_pages(self, pages: int) -> None:
        if pages > self.max_pages:
            raise CountError(CountFailure.PAGE_LIMIT)

    async def _finish(
        self, records, count, pages, searched_since, guild_id, channel_id, version,
        history_ids: set[int] | None = None,
    ) -> CountResult:
        ordered = sorted(
            {item.message_id: item for item in records}.values(),
            key=lambda item: (item.created_at, item.message_id),
        )[-count:]
        if sum(len(item.content.encode("utf-8")) for item in ordered) > self.max_content_bytes:
            raise CountError(CountFailure.INPUT_LIMIT)
        final_version, final_selected = await asyncio.to_thread(self.recent.watches.snapshot, guild_id)
        if final_version != version or channel_id not in final_selected:
            raise CollectionError(CollectionFailure.WATCH_CHANGED)
        return CountResult(
            tuple(ordered), count, count - len(ordered), pages, searched_since,
            sum(item.message_id in (history_ids or ()) for item in ordered),
        )
