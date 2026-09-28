"""Send ordered summary chunks only to their watched Discord text channel."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import discord

from yoyackbot.channel_config import WatchStore, valid_channel
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, PublicationReceipt, SummaryRequest, SummaryResult
from yoyackbot.summary_format import format_summary


class PublicationFailure(Enum):
    CHANNEL_UNAVAILABLE = "channel_unavailable"
    UNWATCHED = "unwatched"
    PERMISSION = "permission"
    UNCERTAIN = "uncertain"


class PartialPublicationError(RuntimeError):
    """Safe delivery status; already-sent chunks must never be retried blindly."""

    def __init__(
        self, reason: PublicationFailure, *, sent_ids: tuple[int, ...], failed_index: int,
        last_success_at: datetime | None,
    ) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.sent_ids = sent_ids
        self.failed_index = failed_index
        self.last_success_at = last_success_at


@dataclass
class DiscordSummaryPublisher:
    client: discord.Client
    watch_store: WatchStore
    settings: Settings
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def publish(
        self, request: SummaryRequest, result: SummaryResult,
        selected: Sequence[MessageRecord],
    ) -> PublicationReceipt:
        parts = format_summary(
            request.requested_range, selected, result, self.settings.timezone,
            limit=self.settings.discord_message_limit, posted_at=self.clock(),
        )
        sent_ids: list[int] = []
        last_success_at: datetime | None = None
        for index, part in enumerate(parts, start=1):
            channel = self.client.get_channel(request.channel_id)
            if (
                channel is None
                or getattr(channel, "type", None) is not discord.ChannelType.text
                or getattr(getattr(channel, "guild", None), "id", None) != request.guild_id
            ):
                raise PartialPublicationError(
                    PublicationFailure.CHANNEL_UNAVAILABLE, sent_ids=tuple(sent_ids),
                    failed_index=index, last_success_at=last_success_at,
                )
            watched = await asyncio.to_thread(self.watch_store.get, request.guild_id)
            if request.channel_id not in watched:
                raise PartialPublicationError(
                    PublicationFailure.UNWATCHED, sent_ids=tuple(sent_ids),
                    failed_index=index, last_success_at=last_success_at,
                )
            if not valid_channel(channel.guild, request.channel_id):
                raise PartialPublicationError(
                    PublicationFailure.PERMISSION, sent_ids=tuple(sent_ids),
                    failed_index=index, last_success_at=last_success_at,
                )
            try:
                sent = await channel.send(
                    part, allowed_mentions=discord.AllowedMentions.none(),
                    suppress_embeds=True,
                )
            except discord.Forbidden as exc:
                raise PartialPublicationError(
                    PublicationFailure.PERMISSION, sent_ids=tuple(sent_ids),
                    failed_index=index, last_success_at=last_success_at,
                ) from exc
            except Exception as exc:  # noqa: BLE001 - response loss means delivery is ambiguous
                raise PartialPublicationError(
                    PublicationFailure.UNCERTAIN, sent_ids=tuple(sent_ids),
                    failed_index=index, last_success_at=last_success_at,
                ) from exc
            if (
                getattr(sent, "id", None) is None
                or getattr(getattr(sent, "channel", None), "id", None) != request.channel_id
                or getattr(sent, "created_at", None) is None
                or sent.created_at.tzinfo is None
            ):
                raise PartialPublicationError(
                    PublicationFailure.UNCERTAIN, sent_ids=tuple(sent_ids),
                    failed_index=index, last_success_at=last_success_at,
                )
            sent_ids.append(sent.id)
            last_success_at = sent.created_at
        assert last_success_at is not None
        return PublicationReceipt(tuple(sent_ids), last_success_at)
