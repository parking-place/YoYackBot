"""Connect verified collection, Codex summary, and same-channel publication."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import discord

from yoyackbot.channel_config import valid_channel
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import EMPTY_NOTICE, CollectionCoordinator, CollectionUnavailable
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore, cooldown_notice
from yoyackbot.count_collection import CountCollector, CountError
from yoyackbot.domain import MessageRecord, SummaryRequest, SummaryResult
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.history import HistoryAdapter, HistoryError
from yoyackbot.input_files import InputFileError
from yoyackbot.job_queue import QueueClosed, QueueFull, QueueWaitExpired, SummaryJobQueue
from yoyackbot.long_range import LongRangeCollector, LongRangeError
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.publisher import DiscordSummaryPublisher, PartialPublicationError
from yoyackbot.range_collection import CollectionError, TimeRangeCollector
from yoyackbot.state import AdmissionKind, ChannelStates
from yoyackbot.watch_gate import ChannelLease
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError

LOGGER = logging.getLogger(__name__)
BUSY_NOTICE = "요약중이오. 좀 기다리시오."
FAILED_NOTICE = "요약을 마치지 못했소. 잠시 후 다시 시도하시오."
INVALIDATED_NOTICE = "채널 주시나 권한이 바뀌어 요약을 멈추었소."
QUEUE_FULL_NOTICE = "요약 요청이 몰렸소. 잠시 후 다시 시도하시오."
QUEUE_TIMEOUT_NOTICE = "요약 대기 시간이 지났소. 다시 시도하시오."
QUEUE_CLOSED_NOTICE = "봇이 종료 중이오. 잠시 후 다시 시도하시오."


class JobInvalidated(RuntimeError):
    """The watched-channel lease or Discord permission changed during a job."""


@dataclass
class SummaryWorkflow:
    collector: CollectionCoordinator
    engine: CodexSummaryEngine
    publisher: DiscordSummaryPublisher
    states: ChannelStates = field(default_factory=ChannelStates)
    queue: SummaryJobQueue | None = None
    closing: bool = False
    _jobs: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)

    @staticmethod
    async def _channel_ready(channel: discord.TextChannel, lease: ChannelLease) -> bool:
        return await asyncio.to_thread(lease.valid) and valid_channel(channel.guild, channel.id)

    async def _summarize_guarded(
        self, messages: Sequence[MessageRecord], *, channel_name: str,
        trigger_message_id: int | None,
        channel: discord.TextChannel, lease: ChannelLease,
    ) -> SummaryResult:
        if self.queue is not None:
            async with await self.queue.acquire():
                if not await self._channel_ready(channel, lease):
                    raise JobInvalidated
                return await self._run_model_guarded(
                    messages, channel_name=channel_name, trigger_message_id=trigger_message_id,
                    channel=channel, lease=lease,
                )
        return await self._run_model_guarded(
            messages, channel_name=channel_name, trigger_message_id=trigger_message_id,
            channel=channel, lease=lease,
        )

    async def _run_model_guarded(
        self, messages: Sequence[MessageRecord], *, channel_name: str,
        trigger_message_id: int | None,
        channel: discord.TextChannel, lease: ChannelLease,
    ) -> SummaryResult:
        model = asyncio.create_task(self.engine.summarize(
            messages, channel_name=channel_name, range_label="선택한 대화",
            trigger_message_id=trigger_message_id,
        ))
        try:
            while True:
                done, _ = await asyncio.wait({model}, timeout=0.5)
                if done:
                    return await model
                if not await self._channel_ready(channel, lease):
                    raise JobInvalidated
        finally:
            if not model.done():
                model.cancel()
                await asyncio.gather(model, return_exceptions=True)

    async def shutdown(self) -> None:
        self.closing = True
        active = [task for task in self._jobs if task is not asyncio.current_task()]
        for task in active:
            task.cancel()
        if self.queue is not None:
            await self.queue.close()
        await asyncio.gather(*active, return_exceptions=True)

    async def run(
        self, request: SummaryRequest, channel: discord.TextChannel,
        lease: ChannelLease, send_notice: Callable[[str], Awaitable[None]],
    ) -> None:
        if self.closing:
            await send_notice(QUEUE_CLOSED_NOTICE)
            return
        task = asyncio.current_task()
        if task is not None:
            self._jobs.add(task)
        try:
            await self._run(request, channel, lease, send_notice)
        finally:
            if task is not None:
                self._jobs.discard(task)

    async def _run(
        self, request: SummaryRequest, channel: discord.TextChannel,
        lease: ChannelLease, send_notice: Callable[[str], Awaitable[None]],
    ) -> None:
        guild_id, channel_id = request.guild_id, request.channel_id
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
            or not await self._channel_ready(channel, lease)
        ):
            await send_notice(FAILED_NOTICE)
            return
        admission = await self.states.admit(guild_id, channel_id)
        if admission.kind is AdmissionKind.BUSY:
            await send_notice(BUSY_NOTICE)
            return
        if admission.kind is AdmissionKind.COOLDOWN:
            await send_notice(cooldown_notice(admission.remaining_seconds))
            return
        completed = False
        try:
            async def can_continue() -> bool:
                return await self._channel_ready(channel, lease)

            outcome = await self.collector.collect(
                channel, guild_id=guild_id, channel_id=channel_id,
                request=request.requested_range,
                can_continue=can_continue,
            )
            if outcome.empty:
                await send_notice(EMPTY_NOTICE)
                return
            if not await can_continue():
                raise JobInvalidated
            result = await self._summarize_guarded(
                outcome.messages, channel_name=channel.name,
                trigger_message_id=request.requested_range.trigger_message_id,
                channel=channel, lease=lease,
            )
            if not await can_continue():
                raise JobInvalidated
            receipt = await self.publisher.publish(request, result, outcome.messages)
            await self.states.finish_success(guild_id, channel_id, receipt.last_success_at)
            completed = True
        except JobInvalidated:
            await send_notice(INVALIDATED_NOTICE)
        except (CollectionError, CollectionUnavailable, HistoryError, CountError, LongRangeError,
                MessageStoreError, WatchStoreError):
            await send_notice(message_for(FailureKind.HISTORY))
        except (CodexRunError, InputFileError):
            await send_notice(message_for(FailureKind.MODEL))
        except PartialPublicationError:
            await send_notice(message_for(FailureKind.SEND))
        except QueueFull:
            await send_notice(QUEUE_FULL_NOTICE)
        except QueueWaitExpired:
            await send_notice(QUEUE_TIMEOUT_NOTICE)
        except QueueClosed:
            await send_notice(QUEUE_CLOSED_NOTICE)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("summary_job_failed type=%s", type(exc).__name__)
            await send_notice(FAILED_NOTICE)
        finally:
            if not completed:
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
        ChannelStates(SQLiteCooldownStore(
            settings.database_path, duration_seconds=settings.success_cooldown_seconds
        )),
        SummaryJobQueue(
            concurrency=settings.codex_concurrency, capacity=settings.queue_capacity,
            wait_seconds=settings.queue_wait_seconds,
        ),
    )
