"""Connect verified collection, Codex summary, and same-channel publication."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import discord

from yoyackbot.backfill import NOT_READY_NOTICE, SQLiteBackfillStore
from yoyackbot.cache_collector import BackfillNotReady, CacheOnlyCollector
from yoyackbot.channel_config import valid_channel
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import EMPTY_NOTICE, CollectionUnavailable
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore, cooldown_notice
from yoyackbot.count_collection import CountError
from yoyackbot.domain import MessageRecord, SummaryMode, SummaryRequest, SummaryResult
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.history import HistoryError
from yoyackbot.input_files import ConversationTooLarge, InputFileError
from yoyackbot.job_queue import QueueClosed, QueueFull, QueueWaitExpired, SummaryJobQueue
from yoyackbot.long_range import LongRangeError
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.ops import RequestMetrics
from yoyackbot.publisher import DiscordSummaryPublisher, PartialPublicationError
from yoyackbot.range_collection import CollectionError
from yoyackbot.scope import busy_notice, start_notice
from yoyackbot.state import AdmissionKind, ChannelStates
from yoyackbot.usage import USAGE_EXHAUSTED_NOTICE
from yoyackbot.watch_gate import ChannelLease
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError

LOGGER = logging.getLogger(__name__)
BUSY_NOTICE = "요약중이오. 좀 기다리시오."
FAILED_NOTICE = "요약을 마치지 못했소. 잠시 후 다시 시도하시오."
INVALIDATED_NOTICE = "채널 주시나 권한이 바뀌어 요약을 멈추었소."
QUEUE_FULL_NOTICE = "요약 요청이 몰렸소. 잠시 후 다시 시도하시오."
QUEUE_TIMEOUT_NOTICE = "요약 대기 시간이 지났소. 다시 시도하시오."
QUEUE_CLOSED_NOTICE = "봇이 종료 중이오. 잠시 후 다시 시도하시오."
INPUT_TOO_LARGE_NOTICE = "요약할 대화가 너무 많소. 기간이나 메시지 개수를 줄여 다시 명하시오."


class JobInvalidated(RuntimeError):
    """The watched-channel lease or Discord permission changed during a job."""


@dataclass
class SummaryWorkflow:
    collector: CacheOnlyCollector
    engine: CodexSummaryEngine
    publisher: DiscordSummaryPublisher
    states: ChannelStates = field(default_factory=ChannelStates)
    queue: SummaryJobQueue | None = None
    readiness: Callable[[int, int], Awaitable[bool]] | None = None
    closing: bool = False
    _jobs: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)

    @staticmethod
    async def _channel_ready(channel: discord.TextChannel, lease: ChannelLease) -> bool:
        return await asyncio.to_thread(lease.valid) and valid_channel(channel.guild, channel.id)

    async def _summarize_guarded(
        self, messages: Sequence[MessageRecord], *, channel_name: str,
        trigger_message_id: int | None, mode: SummaryMode, request_note: str | None,
        channel: discord.TextChannel, lease: ChannelLease, metrics: RequestMetrics,
    ) -> SummaryResult:
        if self.queue is not None:
            waiting_since = time.monotonic()
            try:
                slot = await self.queue.acquire(
                    guild_id=channel.guild.id, size_hint=len(messages),
                )
            finally:
                metrics.queue_ms = max(0, round((time.monotonic() - waiting_since) * 1000))
            async with slot:
                if not await self._channel_ready(channel, lease):
                    raise JobInvalidated
                return await self._run_model_guarded(
                    messages, channel_name=channel_name, trigger_message_id=trigger_message_id,
                    mode=mode, request_note=request_note, channel=channel, lease=lease,
                    metrics=metrics,
                )
        return await self._run_model_guarded(
            messages, channel_name=channel_name, trigger_message_id=trigger_message_id,
            mode=mode, request_note=request_note, channel=channel, lease=lease,
                    metrics=metrics,
        )

    async def _run_model_guarded(
        self, messages: Sequence[MessageRecord], *, channel_name: str,
        trigger_message_id: int | None, mode: SummaryMode, request_note: str | None,
        channel: discord.TextChannel, lease: ChannelLease, metrics: RequestMetrics,
    ) -> SummaryResult:
        model_started = time.monotonic()
        model = asyncio.create_task(self.engine.summarize(
            messages, channel_name=channel_name, range_label="선택한 대화",
            trigger_message_id=trigger_message_id, mode=mode, request_note=request_note,
            on_input_size=lambda size: setattr(metrics, "input_bytes", size),
        ))
        try:
            while True:
                done, _ = await asyncio.wait({model}, timeout=0.5)
                if done:
                    return await model
                if not await self._channel_ready(channel, lease):
                    raise JobInvalidated
        finally:
            metrics.model_ms = max(0, round((time.monotonic() - model_started) * 1000))
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
        metrics = RequestMetrics(request.requested_range.kind.value, mode=request.mode.value)
        task = asyncio.current_task()
        if task is not None:
            self._jobs.add(task)
        try:
            if self.closing:
                metrics.outcome = "queue_closed"
                metrics.error_kind = "queue"
                metrics.failure_detail = "queue_closed"
                await send_notice(QUEUE_CLOSED_NOTICE)
                return
            await self._run(request, channel, lease, send_notice, metrics)
        except asyncio.CancelledError:
            metrics.outcome = "cancelled"
            metrics.model_result = (
                "cancelled" if metrics.model_result == "running" else metrics.model_result
            )
            raise
        finally:
            metrics.emit()
            if task is not None:
                self._jobs.discard(task)

    async def _run(
        self, request: SummaryRequest, channel: discord.TextChannel,
        lease: ChannelLease, send_notice: Callable[[str], Awaitable[None]],
        metrics: RequestMetrics,
    ) -> None:
        guild_id, channel_id = request.guild_id, request.channel_id
        if (
            getattr(channel, "type", None) is not discord.ChannelType.text
            or getattr(channel, "id", None) != channel_id
            or getattr(getattr(channel, "guild", None), "id", None) != guild_id
            or not await self._channel_ready(channel, lease)
        ):
            metrics.outcome = "channel_unavailable"
            metrics.error_kind = "permission"
            metrics.failure_detail = "permission"
            await send_notice(FAILED_NOTICE)
            return
        while True:
            admission = await self.states.admit(
                guild_id, channel_id, scope=request.scope, mode=request.mode,
            )
            if admission.kind is not AdmissionKind.BUSY:
                break
            job = admission.job
            if job is not None and not job.announced.is_set():
                # Never overtake the running request's start notice; if it ended without
                # announcing (not ready or send failure), judge this request afresh.
                await job.announced.wait()
                if await self.states.active(guild_id, channel_id) is not job:
                    continue
            metrics.outcome = "busy"
            await send_notice(
                busy_notice(job.scope, job.mode) if job is not None and job.scope is not None
                else BUSY_NOTICE
            )
            return
        if admission.kind is AdmissionKind.COOLDOWN:
            metrics.outcome = "cooldown"
            await send_notice(cooldown_notice(admission.remaining_seconds))
            return
        completed = False
        try:
            if self.readiness is not None and not await self.readiness(guild_id, channel_id):
                metrics.outcome = "not_ready"
                await send_notice(NOT_READY_NOTICE)
                return
            if request.scope is not None:
                try:
                    await send_notice(start_notice(request.scope, request.mode))
                except (discord.DiscordException, OSError):
                    metrics.outcome = "notice_error"
                    metrics.error_kind = "send"
                    metrics.failure_detail = "send"
                    LOGGER.warning("summary_start_notice_failed")
                    return
            if admission.job is not None:
                admission.job.announced.set()

            async def can_continue() -> bool:
                return await self._channel_ready(channel, lease)

            collecting_since = time.monotonic()
            try:
                outcome = await self.collector.collect(
                    channel, guild_id=guild_id, channel_id=channel_id,
                    request=request.requested_range,
                    can_continue=can_continue,
                )
            finally:
                metrics.collection_ms = max(
                    0, round((time.monotonic() - collecting_since) * 1000)
                )
            metrics.selected_count = len(outcome.messages)
            metrics.cache_count = outcome.cache_count
            metrics.history_count = outcome.history_count
            metrics.history_pages = outcome.pages
            metrics.cache_fallback = outcome.fallback_used
            if outcome.empty:
                metrics.outcome = "empty"
                await send_notice(EMPTY_NOTICE)
                return
            if not await can_continue():
                raise JobInvalidated
            metrics.model_result = "running"
            result = await self._summarize_guarded(
                outcome.messages, channel_name=channel.name,
                trigger_message_id=request.requested_range.trigger_message_id,
                mode=request.mode, request_note=request.request_note, channel=channel,
                lease=lease, metrics=metrics,
            )
            metrics.model_result = "success"
            metrics.rating = result.rating
            if not await can_continue():
                raise JobInvalidated
            receipt = await self.publisher.publish(request, result, outcome.messages)
            metrics.post_result = "success"
            await self.states.finish_success(guild_id, channel_id, receipt.last_success_at)
            metrics.outcome = "success"
            completed = True
        except JobInvalidated:
            metrics.outcome = "invalidated"
            metrics.error_kind = "permission"
            metrics.failure_detail = "permission"
            if metrics.model_result == "running":
                metrics.model_result = "cancelled"
            await send_notice(INVALIDATED_NOTICE)
        except BackfillNotReady:
            metrics.outcome = "not_ready"
            await send_notice(NOT_READY_NOTICE)
        except (CollectionError, CollectionUnavailable, HistoryError, CountError, LongRangeError,
                MessageStoreError, WatchStoreError):
            metrics.outcome = "history_error"
            metrics.error_kind = "history"
            metrics.failure_detail = "history"
            await send_notice(message_for(FailureKind.HISTORY))
        except ConversationTooLarge:
            metrics.outcome = "input_error"
            metrics.model_result = "not_started"
            metrics.error_kind = "input"
            metrics.failure_detail = "input_size"
            await send_notice(INPUT_TOO_LARGE_NOTICE)
        except InputFileError:
            metrics.outcome = "input_error"
            metrics.model_result = "not_started"
            metrics.error_kind = "input"
            metrics.failure_detail = "input_file"
            await send_notice(message_for(FailureKind.MODEL))
        except CodexRunError as exc:
            metrics.outcome = "model_error"
            metrics.model_result = "failure"
            metrics.error_kind = "model"
            metrics.failure_detail = exc.kind.value
            await send_notice(
                USAGE_EXHAUSTED_NOTICE if exc.kind is CodexFailure.USAGE_LIMIT
                else message_for(FailureKind.MODEL)
            )
        except PartialPublicationError:
            metrics.outcome = "post_error"
            metrics.post_result = "partial"
            metrics.error_kind = "send"
            metrics.failure_detail = "send"
            await send_notice(message_for(FailureKind.SEND))
        except QueueFull:
            metrics.outcome = "queue_full"
            metrics.error_kind = "queue"
            metrics.failure_detail = "queue_full"
            metrics.model_result = "not_started"
            await send_notice(QUEUE_FULL_NOTICE)
        except QueueWaitExpired:
            metrics.outcome = "queue_timeout"
            metrics.error_kind = "queue"
            metrics.failure_detail = "queue_timeout"
            metrics.model_result = "not_started"
            await send_notice(QUEUE_TIMEOUT_NOTICE)
        except QueueClosed:
            metrics.outcome = "queue_closed"
            metrics.error_kind = "queue"
            metrics.failure_detail = "queue_closed"
            metrics.model_result = "not_started"
            await send_notice(QUEUE_CLOSED_NOTICE)
        except Exception:  # noqa: BLE001
            metrics.outcome = "unexpected"
            metrics.error_kind = "unexpected"
            metrics.failure_detail = "unexpected"
            LOGGER.warning("summary_job_failed")
            await send_notice(FAILED_NOTICE)
        finally:
            if not completed:
                await self.states.finish(guild_id, channel_id)


def build_workflow(
    settings: Settings, client: discord.Client,
    watches: SQLiteWatchStore, messages: SQLiteMessageStore,
) -> SummaryWorkflow:
    collector = CacheOnlyCollector(
        watches, messages, SQLiteBackfillStore(settings.database_path),
        retention_days=settings.cache_retention_days, max_days=settings.max_days,
        max_count=settings.max_messages, max_content_bytes=settings.max_input_bytes,
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
        readiness=collector.ready,
    )
