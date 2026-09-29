"""Join any nonpersistent older History with the configured verified cache."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

import discord

from yoyackbot.domain import MessageRecord
from yoyackbot.history import HistoryAdapter
from yoyackbot.range_collection import CollectionError, CollectionFailure, TimeRangeCollector


class LongRangeFailure(Enum):
    INVALID_RANGE = "invalid_range"
    TOO_OLD = "too_old"
    INPUT_LIMIT = "input_limit"
    PAGE_LIMIT = "page_limit"


class LongRangeError(RuntimeError):
    def __init__(self, kind: LongRangeFailure) -> None:
        super().__init__(f"Long-range collection stopped: {kind.value}")
        self.kind = kind


@dataclass(frozen=True)
class LongRangeResult:
    messages: tuple[MessageRecord, ...]
    older_count: int
    pages: int
    history_count: int = 0


class LongRangeCollector:
    def __init__(
        self,
        recent: TimeRangeCollector,
        history: HistoryAdapter,
        *,
        retention_days: int = 30,
        max_days: int = 30,
        max_content_bytes: int = 1_000_000,
        max_pages: int = 100,
    ) -> None:
        if not 1 <= retention_days <= 30 or not 1 <= max_days <= 30:
            raise ValueError("Invalid retention or request duration")
        if max_content_bytes < 1 or max_pages < 1:
            raise ValueError("Collection budgets must be positive")
        self.recent = recent
        self.history = history
        self.retention_days = retention_days
        self.max_days = max_days
        self.max_content_bytes = max_content_bytes
        self.max_pages = max_pages

    async def collect(
        self,
        channel: discord.TextChannel,
        *,
        guild_id: int,
        channel_id: int,
        start: datetime,
        end: datetime,
        accepted_at: datetime,
        trigger_message_id: int | None = None,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> LongRangeResult:
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or accepted_at.tzinfo is None
            or start >= end
            or end > accepted_at
        ):
            raise LongRangeError(LongRangeFailure.INVALID_RANGE)
        if start < accepted_at - timedelta(days=self.max_days):
            raise LongRangeError(LongRangeFailure.TOO_OLD)
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
        await asyncio.to_thread(self.recent.store.prune_before, cutoff)
        older: tuple[MessageRecord, ...] = ()
        history_ids: set[int] = set()
        pages = 0
        if start < cutoff:
            older_end = min(end, cutoff)
            if start < older_end:
                old_result = await self.history.collect(
                    channel,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    start=start,
                    end=older_end,
                    trigger_message_id=trigger_message_id,
                    can_continue=can_continue,
                )
                older = old_result.messages
                history_ids.update(item.message_id for item in older)
                pages += old_result.pages
                self._check_budget(older, pages)

        current: tuple[MessageRecord, ...] = ()
        recent_start = max(start, cutoff)
        if recent_start < end:
            current_result = await self.recent.collect(
                channel,
                guild_id=guild_id,
                channel_id=channel_id,
                start=recent_start,
                end=end,
                trigger_message_id=trigger_message_id,
                can_continue=can_continue,
            )
            current = current_result.messages
            history_ids.update(current_result.history_ids)
            pages += current_result.pages
        combined = tuple(sorted({item.message_id: item for item in (*older, *current)}.values(),
                                key=lambda item: (item.created_at, item.message_id)))
        self._check_budget(combined, pages)
        final_version, final_selected = await asyncio.to_thread(self.recent.watches.snapshot, guild_id)
        if final_version != version or channel_id not in final_selected:
            raise CollectionError(CollectionFailure.WATCH_CHANGED)
        return LongRangeResult(
            combined, len(older), pages,
            sum(item.message_id in history_ids for item in combined),
        )

    def _check_budget(self, records: tuple[MessageRecord, ...], pages: int) -> None:
        if pages > self.max_pages:
            raise LongRangeError(LongRangeFailure.PAGE_LIMIT)
        if sum(len(item.content.encode("utf-8")) for item in records) > self.max_content_bytes:
            raise LongRangeError(LongRangeFailure.INPUT_LIMIT)
