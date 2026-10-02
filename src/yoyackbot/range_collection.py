"""Fill only missing verified time intervals before reading a channel request."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import discord

from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.history import HistoryAdapter
from yoyackbot.message_store import SQLiteMessageStore, _datetime
from yoyackbot.watch_store import SQLiteWatchStore


class CollectionFailure(Enum):
    UNWATCHED = "unwatched"
    WATCH_CHANGED = "watch_changed"
    CHANNEL_MISMATCH = "channel_mismatch"
    INCOMPLETE = "incomplete"


class CollectionError(RuntimeError):
    def __init__(self, kind: CollectionFailure) -> None:
        super().__init__(f"History collection stopped: {kind.value}")
        self.kind = kind


@dataclass(frozen=True)
class TimeCollectionResult:
    messages: tuple[MessageRecord, ...]
    queried: tuple[CoverageInterval, ...]
    pages: int
    history_ids: frozenset[int] = frozenset()


class TimeRangeCollector:
    def __init__(
        self,
        store: SQLiteMessageStore,
        watches: SQLiteWatchStore,
        history: HistoryAdapter,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.watches = watches
        self.history = history
        self.clock = clock or (lambda: datetime.now(UTC))

    async def collect(
        self,
        channel: discord.TextChannel,
        *,
        guild_id: int,
        channel_id: int,
        start: datetime,
        end: datetime,
        trigger_message_id: int | None = None,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> TimeCollectionResult:
        request = CoverageInterval(channel_id, start, end)
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
        ):
            raise CollectionError(CollectionFailure.CHANNEL_MISMATCH)
        version, selected = await asyncio.to_thread(self.watches.snapshot, guild_id)
        if channel_id not in selected:
            raise CollectionError(CollectionFailure.UNWATCHED)
        gaps = await asyncio.to_thread(self.store.missing, guild_id, request)
        pages = 0
        history_ids: set[int] = set()
        for gap in gaps:
            fetched_after = _datetime(await asyncio.to_thread(
                self.store.history_boundary, guild_id, channel_id, at=self.clock(),
            ))
            result = await self.history.collect(
                channel,
                guild_id=guild_id,
                channel_id=channel_id,
                start=gap.start,
                end=gap.end,
                trigger_message_id=trigger_message_id,
                can_continue=can_continue,
            )
            if not result.exhausted:
                raise CollectionError(CollectionFailure.INCOMPLETE)
            completed = await asyncio.to_thread(
                self.store.commit_history_complete,
                guild_id,
                gap,
                result.messages,
                exhausted=True,
                expected_version=version,
                verified_at=self.clock(),
                fetched_after=fetched_after,
            )
            if not completed:
                raise CollectionError(CollectionFailure.WATCH_CHANGED)
            history_ids.update(item.message_id for item in result.messages)
            pages += result.pages
        messages = await asyncio.to_thread(self.store.recent, guild_id, channel_id, start, end)
        final_version, final_selected = await asyncio.to_thread(self.watches.snapshot, guild_id)
        if final_version != version or channel_id not in final_selected:
            raise CollectionError(CollectionFailure.WATCH_CHANGED)
        return TimeCollectionResult(
            tuple(message for message in messages if message.message_id != trigger_message_id),
            tuple(gaps),
            pages,
            frozenset(history_ids),
        )
