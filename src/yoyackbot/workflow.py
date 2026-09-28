"""Connect verified collection, Codex summary, and same-channel publication."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import discord

from yoyackbot.channel_config import valid_channel
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.collection import CollectionCoordinator, EMPTY_NOTICE
from yoyackbot.config import Settings
from yoyackbot.count_collection import CountCollector
from yoyackbot.domain import SummaryRequest
from yoyackbot.history import HistoryAdapter
from yoyackbot.long_range import LongRangeCollector
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.publisher import DiscordSummaryPublisher
from yoyackbot.range_collection import TimeRangeCollector
from yoyackbot.state import ChannelStates
from yoyackbot.watch_gate import ChannelLease
from yoyackbot.watch_store import SQLiteWatchStore

LOGGER = logging.getLogger(__name__)
BUSY_NOTICE = "요약중이오. 좀 기다리시오."
FAILED_NOTICE = "요약을 마치지 못했소. 잠시 후 다시 시도하시오."


@dataclass
class SummaryWorkflow:
    collector: CollectionCoordinator
    engine: CodexSummaryEngine
    publisher: DiscordSummaryPublisher
    states: ChannelStates = field(default_factory=ChannelStates)

    async def run(
        self, request: SummaryRequest, channel: discord.TextChannel,
        lease: ChannelLease, send_notice: Callable[[str], Awaitable[None]],
    ) -> None:
        guild_id, channel_id = request.guild_id, request.channel_id
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
            or not await asyncio.to_thread(lease.valid)
            or not valid_channel(channel.guild, channel_id)
        ):
            await send_notice(FAILED_NOTICE)
            return
        if not await self.states.begin(guild_id, channel_id):
            await send_notice(BUSY_NOTICE)
            return
        try:
            outcome = await self.collector.collect(
                channel, guild_id=guild_id, channel_id=channel_id,
                request=request.requested_range,
            )
            if outcome.empty:
                await send_notice(EMPTY_NOTICE)
                return
            if not await asyncio.to_thread(lease.valid):
                await send_notice(FAILED_NOTICE)
                return
            result = await self.engine.summarize(
                outcome.messages, channel_name=channel.name,
                range_label="선택한 대화", trigger_message_id=request.requested_range.trigger_message_id,
            )
            if not await asyncio.to_thread(lease.valid):
                await send_notice(FAILED_NOTICE)
                return
            await self.publisher.publish(request, result, outcome.messages)
        except Exception as exc:  # Error-specific recovery is added in P3.
            LOGGER.warning("summary_job_failed type=%s", type(exc).__name__)
            await send_notice(FAILED_NOTICE)
        finally:
            await self.states.finish(guild_id, channel_id)


def build_workflow(
    settings: Settings, client: discord.Client,
    watches: SQLiteWatchStore, messages: SQLiteMessageStore,
) -> SummaryWorkflow:
    history = HistoryAdapter(max_pages=settings.max_history_pages)
    recent = TimeRangeCollector(messages, watches, history)
    collector = CollectionCoordinator(
        watches,
        LongRangeCollector(recent, history, max_content_bytes=settings.max_input_bytes),
        CountCollector(
            recent, history, max_count=settings.max_messages,
            max_content_bytes=settings.max_input_bytes,
            max_pages=settings.max_history_pages,
        ),
        history, max_count=settings.max_messages, max_content_bytes=settings.max_input_bytes,
        max_pages=settings.max_history_pages,
    )
    return SummaryWorkflow(
        collector, CodexSummaryEngine.from_settings(settings),
        DiscordSummaryPublisher(client, watches, settings),
    )
