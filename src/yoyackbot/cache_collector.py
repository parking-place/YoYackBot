"""Serve ordinary summaries from the completed channel cache without Discord History."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

import discord

from yoyackbot.backfill import SQLiteBackfillStore, summary_ready
from yoyackbot.collection import CollectionOutcome, CollectionUnavailable
from yoyackbot.count_collection import CountError, CountFailure
from yoyackbot.domain import RangeRequest, RequestKind
from yoyackbot.input_files import ConversationTooLarge
from yoyackbot.long_range import LongRangeError, LongRangeFailure
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.range_collection import CollectionError, CollectionFailure
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError


class BackfillNotReady(CollectionUnavailable):
    """The first full collection or a gap repair has not completed."""


class CacheOnlyCollector:
    def __init__(
        self, watches: SQLiteWatchStore, messages: SQLiteMessageStore,
        backfills: SQLiteBackfillStore, *, retention_days: int = 30,
        max_days: int = 30, max_count: int = 1000, max_content_bytes: int = 1_000_000,
    ) -> None:
        if min(retention_days, max_days, max_count, max_content_bytes) < 1:
            raise ValueError("Collection limits must be positive")
        self.watches = watches
        self.messages = messages
        self.backfills = backfills
        self.retention_days = retention_days
        self.max_days = max_days
        self.max_count = max_count
        self.max_content_bytes = max_content_bytes

    async def collect(
        self, channel: discord.TextChannel, *, guild_id: int, channel_id: int,
        request: RangeRequest,
        can_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> CollectionOutcome:
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
        ):
            raise CollectionError(CollectionFailure.CHANNEL_MISMATCH)
        try:
            version, selected = await asyncio.to_thread(self.watches.snapshot, guild_id)
            if channel_id not in selected:
                raise CollectionError(CollectionFailure.UNWATCHED)
            state = await asyncio.to_thread(self.backfills.get, guild_id, channel_id)
            if not summary_ready(state):
                raise BackfillNotReady("Initial collection is not complete")
            if can_continue is not None and not await can_continue():
                raise CollectionError(CollectionFailure.WATCH_CHANGED)
            floor = request.accepted_at - timedelta(days=self.retention_days)
            if request.kind is RequestKind.TIME:
                assert request.start is not None
                if request.start < max(
                    floor, request.accepted_at - timedelta(days=self.max_days)
                ):
                    raise LongRangeError(LongRangeFailure.TOO_OLD)
                start = request.start
                rows = await asyncio.to_thread(
                    self.messages.recent, guild_id, channel_id, start, request.accepted_at
                )
                selected_rows = tuple(
                    row for row in rows if row.message_id != request.trigger_message_id
                )
                shortage = 0
                searched_since = start
            else:
                assert request.count is not None
                if request.count > self.max_count:
                    raise CountError(CountFailure.INVALID_COUNT)
                start = max(floor, request.accepted_at - timedelta(days=self.max_days))
                rows = await asyncio.to_thread(
                    self.messages.latest, guild_id, channel_id, start, request.accepted_at,
                    request.count, exclude_id=request.trigger_message_id,
                )
                selected_rows = tuple(sorted(rows, key=lambda row: (row.created_at, row.message_id)))
                shortage = request.count - len(selected_rows)
                searched_since = start if shortage else selected_rows[0].created_at
            if sum(len(row.content.encode("utf-8")) for row in selected_rows) > self.max_content_bytes:
                raise ConversationTooLarge("Cached conversation exceeds configured input size")
            final_version, final_selected = await asyncio.to_thread(self.watches.snapshot, guild_id)
            final_state = await asyncio.to_thread(self.backfills.get, guild_id, channel_id)
            if (
                version != final_version or channel_id not in final_selected
                or not summary_ready(final_state) or final_state.token != state.token
                or (can_continue is not None and not await can_continue())
            ):
                raise CollectionError(CollectionFailure.WATCH_CHANGED)
            return CollectionOutcome(
                selected_rows, shortage, searched_since, 0, False,
                cache_count=len(selected_rows), history_count=0,
            )
        except WatchStoreError as exc:
            raise CollectionUnavailable("Channel settings are unavailable") from exc
