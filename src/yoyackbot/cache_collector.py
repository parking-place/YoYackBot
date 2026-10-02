"""Serve ordinary summaries from the completed channel cache without Discord History."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import discord

from yoyackbot.backfill import BackfillError, SQLiteBackfillStore, summary_ready
from yoyackbot.collection import CollectionOutcome, CollectionUnavailable
from yoyackbot.count_collection import CountError, CountFailure
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind
from yoyackbot.input_files import ConversationTooLarge
from yoyackbot.long_range import LongRangeError, LongRangeFailure
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.range_collection import CollectionError, CollectionFailure
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError


class BackfillNotReady(CollectionUnavailable):
    """The first full collection or a gap repair has not completed."""


@dataclass(frozen=True)
class CacheCollectionOutcome(CollectionOutcome):
    """Keep the verified cache generation attached to this immutable selection."""

    cache_generation: tuple[str, int] | None = None


class CacheOnlyCollector:
    def __init__(
        self, watches: SQLiteWatchStore, messages: SQLiteMessageStore,
        backfills: SQLiteBackfillStore, *, retention_days: int = 30,
        max_days: int = 30, max_count: int = 1000, max_content_bytes: int = 1_000_000,
        clock: Callable[[], datetime] | None = None,
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
        self.clock = clock or (lambda: datetime.now(UTC))

    def cutoff(self) -> datetime:
        return self.clock() - timedelta(days=self.retention_days)

    async def generation(self, guild_id: int, channel_id: int) -> tuple[str, int] | None:
        """Read phase, validation generation and pending ranges in one DB snapshot."""
        try:
            state, generation, pending = await asyncio.to_thread(
                self.backfills.readiness_snapshot, guild_id, channel_id, cutoff=self.cutoff(),
            )
        except BackfillError as exc:
            raise CollectionUnavailable("Cache verification state is unavailable") from exc
        if not summary_ready(state) or pending:
            return None
        assert state is not None
        return state.token, generation

    async def ready(self, guild_id: int, channel_id: int) -> bool:
        """True only when the channel is past initial collection and any gap recheck."""
        return await self.generation(guild_id, channel_id) is not None

    async def validate_selection(
        self, guild_id: int, channel_id: int,
        generation: tuple[str, int] | None, messages: tuple[MessageRecord, ...],
    ) -> None:
        """Do not send a pre-reconnect or newly expired selection to the model/publication."""
        if generation is None or await self.generation(guild_id, channel_id) != generation:
            raise BackfillNotReady("Cache verification changed during this request")
        cutoff = self.cutoff()
        if any(message.created_at < cutoff for message in messages):
            raise LongRangeError(LongRangeFailure.TOO_OLD)

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
            generation = await self.generation(guild_id, channel_id)
            if generation is None:
                raise BackfillNotReady("Initial collection is not complete")
            if can_continue is not None and not await can_continue():
                raise CollectionError(CollectionFailure.WATCH_CHANGED)
            floor = self.cutoff()
            if request.kind is RequestKind.TIME:
                assert request.start is not None
                if request.start < max(
                    request.accepted_at - timedelta(days=self.retention_days),
                    request.accepted_at - timedelta(days=self.max_days),
                ):
                    raise LongRangeError(LongRangeFailure.TOO_OLD)
                start = min(request.accepted_at, max(request.start, floor))
                # Bounded reads refuse an oversized range before the whole period is loaded.
                selected_rows = tuple(
                    row for row in await asyncio.to_thread(
                        self.messages.recent, guild_id, channel_id, start, request.accepted_at,
                        exclude_id=request.trigger_message_id, max_bytes=self.max_content_bytes,
                    )
                    if request.anchor_message_id is None or row.created_at > start
                    or row.message_id >= request.anchor_message_id
                )
                shortage = 0
                searched_since = start
            else:
                assert request.count is not None
                if request.count > self.max_count:
                    raise CountError(CountFailure.INVALID_COUNT)
                start = min(request.accepted_at, max(
                    floor, request.accepted_at - timedelta(days=self.max_days),
                ))
                rows = await asyncio.to_thread(
                    self.messages.latest, guild_id, channel_id, start, request.accepted_at,
                    request.count, exclude_id=request.trigger_message_id,
                    max_bytes=self.max_content_bytes,
                )
                selected_rows = tuple(sorted(rows, key=lambda row: (row.created_at, row.message_id)))
                shortage = request.count - len(selected_rows)
                searched_since = start if shortage else selected_rows[0].created_at
            if sum(len(row.content.encode("utf-8")) for row in selected_rows) > self.max_content_bytes:
                raise ConversationTooLarge("Cached conversation exceeds configured input size")
            final_version, final_selected = await asyncio.to_thread(self.watches.snapshot, guild_id)
            if (
                version != final_version or channel_id not in final_selected
                or (can_continue is not None and not await can_continue())
            ):
                raise CollectionError(CollectionFailure.WATCH_CHANGED)
            final_generation = await self.generation(guild_id, channel_id)
            if final_generation != generation:
                raise BackfillNotReady("Cache verification changed during selection")
            # A read can wait on SQLite while the retention boundary advances. Removing
            # expired rows respects policy; pending/unverified rows are never filtered away.
            final_floor = self.cutoff()
            selected_rows = tuple(row for row in selected_rows if row.created_at >= final_floor)
            searched_since = min(request.accepted_at, max(searched_since, final_floor))
            if request.kind is RequestKind.COUNT:
                assert request.count is not None
                shortage = request.count - len(selected_rows)
            return CacheCollectionOutcome(
                selected_rows, shortage, searched_since, 0, False,
                cache_count=len(selected_rows), history_count=0,
                cache_generation=generation,
            )
        except WatchStoreError as exc:
            raise CollectionUnavailable("Channel settings are unavailable") from exc
