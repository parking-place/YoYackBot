"""Discord Gateway entry point and conservative message boundary."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol

import discord
from discord import app_commands

from yoyackbot import __version__
from yoyackbot.backfill import (
    NOT_READY_NOTICE,
    BackfillError,
    BackfillNotifier,
    BackfillPageScheduler,
    BackfillState,
    InitialBackfill,
    SQLiteBackfillStore,
    round_robin_backfills,
    summary_ready,
)
from yoyackbot.channel_config import (
    MemoryWatchStore,
    WatchStore,
    install_channel_commands,
    valid_channel,
)
from yoyackbot.codex import CodexContractError
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, SummaryMode, SummaryRequest
from yoyackbot.health import write_heartbeat
from yoyackbot.input_files import cleanup_abandoned_workspaces, single_gateway
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.parser import (
    CommandLimitError,
    CommandSyntaxError,
    RouteKind,
    help_text,
    route_trigger,
    split_mode,
)
from yoyackbot.range_request import resolve_range
from yoyackbot.scope import RangeScope, describe_range
from yoyackbot.status_report import StatusReport, collect_status, status_message
from yoyackbot.usage import (
    USAGE_UNAVAILABLE_NOTICE,
    UsageSnapshot,
    UsageUnavailable,
    read_account_usage,
    usage_message,
)
from yoyackbot.watch_gate import UNAVAILABLE_NOTICE, ChannelLease, WatchGate
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError
from yoyackbot.workflow import SummaryWorkflow, build_workflow

LOGGER = logging.getLogger(__name__)
PREVIEW_NOTICE = "요약 요청을 해석했소. 실제 요약 기능은 아직 준비 중이오."


class MessageCandidate(Protocol):
    guild: object | None
    channel: object
    author: object
    webhook_id: int | None
    type: discord.MessageType


class MessageClass(Enum):
    HUMAN_TEXT = "human_text"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    BOT = "bot"
    WEBHOOK = "webhook"
    SYSTEM = "system"


def classify_message(message: MessageCandidate) -> MessageClass:
    """Classify at ingress without reading or logging the message body."""
    if message.guild is None or getattr(message.channel, "type", None) is not discord.ChannelType.text:
        return MessageClass.UNSUPPORTED_CHANNEL
    if message.webhook_id is not None:
        return MessageClass.WEBHOOK
    if getattr(message.author, "bot", False):
        return MessageClass.BOT
    if message.type not in {discord.MessageType.default, discord.MessageType.reply}:
        return MessageClass.SYSTEM
    return MessageClass.HUMAN_TEXT


def required_intents() -> discord.Intents:
    """Request only guild, guild-message, and message-content events."""
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    return intents


class YoYackClient(discord.Client):
    def __init__(
        self,
        *,
        observe_channel_id: int | None = None,
        watch_store: WatchStore | None = None,
        message_store: SQLiteMessageStore | None = None,
        dev_guild_id: int | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
        summary_workflow: SummaryWorkflow | None = None,
        usage_reader: Callable[[], Awaitable[UsageSnapshot]] | None = None,
    ) -> None:
        super().__init__(intents=required_intents(), member_cache_flags=discord.MemberCacheFlags.none())
        self.observe_channel_id = observe_channel_id
        self.ready_event = asyncio.Event()
        self.accepted_events = 0
        self.nonempty_content_events = 0
        self.connection_count = 0
        self.watch_store = watch_store or MemoryWatchStore()
        self.message_store = message_store
        self.watch_gate = WatchGate(self.watch_store)
        self.dev_guild_id = dev_guild_id
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.summary_workflow = summary_workflow
        self.usage_reader = usage_reader
        self._usage_lock = asyncio.Lock()
        self.backfill_store = (
            SQLiteBackfillStore(settings.database_path)
            if settings is not None and isinstance(self.watch_store, SQLiteWatchStore)
            and message_store is not None else None
        )
        self.initial_backfill = (
            InitialBackfill(self.backfill_store, clock=self.clock)
            if self.backfill_store is not None else None
        )
        self.backfill_notifier = (
            BackfillNotifier(
                self.backfill_store,
                bot_user_id=lambda: self.user.id if self.user is not None else None,
                clock=self.clock,
            ) if self.backfill_store is not None else None
        )
        self.backfill_scheduler = BackfillPageScheduler() if self.backfill_store else None
        self._backfill_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._disconnected_at: datetime | None = None
        self._synced_guild_ids: set[int] = set()
        self.tree = app_commands.CommandTree(self)
        install_channel_commands(self.tree, self.watch_store)

    async def setup_hook(self) -> None:
        if self.settings is not None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self.message_store is not None and self.settings is not None:
            await self._prune_once()
            await self._mark_recheck("startup")
            self._cleanup_task = asyncio.create_task(self._prune_loop())
        if self.backfill_store is not None:
            seeded = await asyncio.to_thread(self.backfill_store.ensure_existing)
            LOGGER.info("initial_backfill_seeded count=%d", seeded)
            gaps = await asyncio.to_thread(
                self.backfill_store.schedule_ready_recheck, end=self.clock()
            )
            LOGGER.info("initial_backfill_recheck_scheduled count=%d", gaps)
            self._backfill_task = asyncio.create_task(self._backfill_loop())
        if self.dev_guild_id is not None:
            await self._sync_guild_commands(discord.Object(id=self.dev_guild_id))
        else:
            commands = await self.tree.sync()
            LOGGER.info("commands_synced count=%d", len(commands))

    async def _sync_guild_commands(self, guild: discord.abc.Snowflake) -> None:
        if guild.id in self._synced_guild_ids:
            return
        self.tree.copy_global_to(guild=guild)
        commands = await self.tree.sync(guild=guild)
        self._synced_guild_ids.add(guild.id)
        LOGGER.info("commands_synced count=%d", len(commands))

    async def on_ready(self) -> None:
        self.connection_count += 1
        await self._resume_accessible_backfills()
        if self._disconnected_at is not None:
            await self._schedule_backfill_gap(self._disconnected_at)
            await self._mark_recheck("gateway_gap")
            self._disconnected_at = None
        self.ready_event.set()
        self._write_heartbeat()
        LOGGER.info("gateway_ready guild_count=%d", len(self.guilds))
        if self.dev_guild_id is not None:
            for guild in self.guilds:
                try:
                    await self._sync_guild_commands(guild)
                except discord.HTTPException:
                    LOGGER.warning("guild_commands_sync_failed")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if self.dev_guild_id is not None:
            try:
                await self._sync_guild_commands(guild)
            except discord.HTTPException:
                LOGGER.warning("guild_commands_sync_failed")

    async def on_resumed(self) -> None:
        LOGGER.info("gateway_resumed")
        await self._resume_accessible_backfills()
        if self._disconnected_at is not None:
            await self._schedule_backfill_gap(self._disconnected_at)
            await self._mark_recheck("gateway_gap")
            self._disconnected_at = None
        self.ready_event.set()
        self._write_heartbeat()

    async def on_disconnect(self) -> None:
        LOGGER.info("gateway_disconnected")
        self.ready_event.clear()
        self._write_heartbeat()
        self._disconnected_at = self.clock()

    async def close(self) -> None:
        self.ready_event.clear()
        if self._backfill_task is not None:
            self._backfill_task.cancel()
            await asyncio.gather(self._backfill_task, return_exceptions=True)
            self._backfill_task = None
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
            self._heartbeat_task = None
        self._write_heartbeat()
        if self.summary_workflow is not None:
            await self.summary_workflow.shutdown()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        await super().close()

    def _write_heartbeat(self) -> None:
        if self.settings is not None:
            try:
                write_heartbeat(self.settings.input_directory, gateway_ready=self.ready_event.is_set())
            except OSError:
                LOGGER.warning("gateway_health_write_failed")

    async def _heartbeat_loop(self) -> None:
        while True:
            self._write_heartbeat()
            await asyncio.sleep(10)

    async def _prune_once(self) -> None:
        if self.message_store is None or self.settings is None:
            return
        cutoff = self.clock() - timedelta(days=self.settings.cache_retention_days)
        try:
            deleted = await asyncio.to_thread(self.message_store.prune_before, cutoff)
            LOGGER.info("cache_cleanup deleted=%d", deleted)
        except MessageStoreError:
            LOGGER.warning("cache_cleanup_failed")

    async def _mark_recheck(self, reason: str) -> None:
        if self.message_store is None or self.settings is None:
            return
        end = self.clock()
        start = end - timedelta(days=self.settings.cache_retention_days)
        try:
            count = await asyncio.to_thread(
                self.message_store.mark_all_watched_recheck, start, end, reason=reason
            )
            LOGGER.info("cache_recheck_marked count=%d reason=%s", count, reason)
        except MessageStoreError:
            LOGGER.warning("cache_recheck_mark_failed")

    async def _schedule_backfill_gap(self, disconnected_at: datetime) -> None:
        if self.backfill_store is None:
            return
        try:
            count = await asyncio.to_thread(
                self.backfill_store.schedule_ready_recheck,
                start=disconnected_at, end=self.clock(),
            )
            LOGGER.info("backfill_gap_scheduled count=%d", count)
        except BackfillError:
            LOGGER.warning("backfill_gap_schedule_failed")

    async def _resume_accessible_backfills(self) -> None:
        if self.backfill_store is None:
            return
        for guild in self.guilds:
            try:
                watched = await asyncio.to_thread(self.watch_store.get, guild.id)
                for channel_id in watched:
                    if valid_channel(guild, channel_id):
                        await asyncio.to_thread(
                            self.backfill_store.resume_blocked, guild.id, channel_id
                        )
            except (BackfillError, WatchStoreError):
                LOGGER.warning("backfill_permission_resume_failed")

    async def on_guild_channel_update(
        self, _before: discord.abc.GuildChannel, after: discord.abc.GuildChannel
    ) -> None:
        if self.backfill_store is None or not isinstance(after, discord.TextChannel):
            return
        if valid_channel(after.guild, after.id):
            try:
                await asyncio.to_thread(
                    self.backfill_store.resume_blocked, after.guild.id, after.id
                )
            except BackfillError:
                LOGGER.warning("backfill_permission_resume_failed")

    async def on_guild_role_update(self, _before: discord.Role, after: discord.Role) -> None:
        if self.backfill_store is None:
            return
        try:
            watched = await asyncio.to_thread(self.watch_store.get, after.guild.id)
            for channel_id in watched:
                if valid_channel(after.guild, channel_id):
                    await asyncio.to_thread(
                        self.backfill_store.resume_blocked, after.guild.id, channel_id
                    )
        except (BackfillError, WatchStoreError):
            LOGGER.warning("backfill_permission_resume_failed")

    async def _prune_loop(self) -> None:
        assert self.settings is not None
        while True:
            await asyncio.sleep(self.settings.cache_cleanup_interval_seconds)
            await self._prune_once()

    async def _backfill_loop(self) -> None:
        assert self.backfill_store is not None and self.initial_backfill is not None
        assert self.backfill_notifier is not None and self.backfill_scheduler is not None
        while True:
            await self.ready_event.wait()
            try:
                pending = await asyncio.to_thread(self.backfill_store.pending, self.clock())
            except BackfillError:
                LOGGER.warning("initial_backfill_state_unavailable")
                await asyncio.sleep(5)
                continue
            await asyncio.gather(*(
                self._backfill_one(state) for state in round_robin_backfills(pending)
            ))
            await asyncio.sleep(0.05 if pending else 3)

    async def _backfill_one(self, state: BackfillState) -> bool:
        assert self.backfill_store is not None and self.initial_backfill is not None
        assert self.backfill_notifier is not None and self.backfill_scheduler is not None

        async def process() -> bool:
            if not self.ready_event.is_set():
                return False
            channel = self.get_channel(state.channel_id)
            if (
                not isinstance(channel, discord.TextChannel)
                or channel.guild.id != state.guild_id
                or not valid_channel(channel.guild, channel.id)
            ):
                await asyncio.to_thread(
                    self.backfill_store.defer, state,
                    until=self.clock() + timedelta(minutes=1),
                )
                return False
            try:
                if state.first_watch and state.started_notice_id is None and not state.ready:
                    return await self.backfill_notifier.ensure(channel, state, ready=False)
                if state.ready:
                    if state.first_watch and state.ready_notice_id is None:
                        return await self.backfill_notifier.ensure(channel, state, ready=True)
                    return True
                return await asyncio.wait_for(
                    self.initial_backfill.step(
                        channel, state,
                        can_continue=lambda: valid_channel(channel.guild, channel.id),
                    ), timeout=60,
                )
            except BackfillError as exc:
                if not exc.retryable:
                    LOGGER.warning("initial_backfill_blocked kind=%s", exc.kind)
                    await asyncio.to_thread(
                        self.backfill_store.block, state, reason=exc.kind
                    )
                    return False
                LOGGER.warning("initial_backfill_page_deferred")
            except (MessageStoreError, TimeoutError):
                LOGGER.warning("initial_backfill_page_deferred")
            await asyncio.to_thread(
                self.backfill_store.defer, state,
                until=self.clock() + timedelta(seconds=30),
            )
            return False

        return await self.backfill_scheduler.run(state.guild_id, process)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        try:
            if await asyncio.to_thread(self.watch_store.remove_channel, channel.guild.id, channel.id):
                LOGGER.info("watched_channel_deleted")
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_delete_cleanup_failed")

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        try:
            await asyncio.to_thread(self.watch_store.remove_guild, guild.id)
            LOGGER.info("watched_guild_removed")
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_guild_cleanup_failed")

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if classify_message(after) is not MessageClass.HUMAN_TEXT or after.guild is None:
            return
        await self.watch_gate.ingest(
            after.guild.id,
            after.channel.id,
            after,
            self.on_watched_message,
        )

    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if self.message_store is None or payload.guild_id is None:
            return
        content = payload.data.get("content")
        if not isinstance(content, str):
            return
        raw_edited = payload.data.get("edited_timestamp")
        try:
            edited_at = datetime.fromisoformat(raw_edited) if isinstance(raw_edited, str) else self.clock()
        except ValueError:
            edited_at = self.clock()
        if edited_at.tzinfo is None:
            edited_at = self.clock()
        try:
            await asyncio.to_thread(
                self.message_store.update_content,
                payload.guild_id,
                payload.channel_id,
                payload.message_id,
                content,
                edited_at=edited_at,
                cached_at=self.clock(),
            )
        except MessageStoreError:
            LOGGER.warning("message_edit_sync_failed")

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if self.message_store is None or payload.guild_id is None:
            return
        try:
            await asyncio.to_thread(
                self.message_store.delete_many,
                payload.guild_id,
                payload.channel_id,
                {payload.message_id},
            )
        except MessageStoreError:
            LOGGER.warning("message_delete_sync_failed")

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if self.message_store is None or payload.guild_id is None:
            return
        try:
            await asyncio.to_thread(
                self.message_store.delete_many,
                payload.guild_id,
                payload.channel_id,
                set(payload.message_ids),
            )
        except MessageStoreError:
            LOGGER.warning("message_bulk_delete_sync_failed")

    async def on_message(self, message: discord.Message) -> None:
        if classify_message(message) is not MessageClass.HUMAN_TEXT:
            return
        self.accepted_events += 1
        if message.content:
            self.nonempty_content_events += 1
        if self.observe_channel_id is not None and message.channel.id == self.observe_channel_id:
            LOGGER.info("gateway_test_human_event has_content=%s", bool(message.content))
        route = route_trigger(message.content)
        if route.kind is RouteKind.HELP:
            await message.channel.send(
                help_text(self.settings), allowed_mentions=discord.AllowedMentions.none()
            )
            return
        assert message.guild is not None
        if route.kind in (RouteKind.USAGE, RouteKind.STATUS):
            async def send_usage(notice: str) -> None:
                await message.channel.send(notice, allowed_mentions=discord.AllowedMentions.none())

            async def handle_usage(_lease: ChannelLease) -> None:
                if route.kind is RouteKind.USAGE:
                    await send_usage(await self.usage_reply())
                else:
                    await send_usage(await self.status_reply(message.guild.id))

            await self.watch_gate.request(
                message.guild.id,
                message.channel.id,
                is_help=False,
                help_reply=lambda: send_usage(help_text(self.settings)),
                unwatched_reply=send_usage,
                unavailable_reply=send_usage,
                summarize=handle_usage,
            )
            return
        if route.kind is RouteKind.SUMMARY:
            accepted_at = self.clock()

            async def send_notice(notice: str) -> None:
                await message.channel.send(notice, allowed_mentions=discord.AllowedMentions.none())

            async def handle_request(lease: ChannelLease) -> None:
                if self.settings is None:
                    await send_notice(UNAVAILABLE_NOTICE)
                    return
                if self.backfill_store is not None:
                    try:
                        backfill = await asyncio.to_thread(
                            self.backfill_store.get, message.guild.id, message.channel.id
                        )
                    except BackfillError:
                        await send_notice(UNAVAILABLE_NOTICE)
                        return
                    if not summary_ready(backfill):
                        await send_notice(NOT_READY_NOTICE)
                        return
                try:
                    range_text, mode = split_mode(route.options)
                    scope = describe_range(range_text, self.settings)
                    request = resolve_range(
                        range_text,
                        self.settings,
                        accepted_at,
                        trigger_message_id=getattr(message, "id", None),
                    )
                except (CommandSyntaxError, CommandLimitError) as exc:
                    await send_notice(str(exc))
                    return
                await self.on_summary_request(message, request, lease, mode=mode, scope=scope)

            await self.watch_gate.request(
                message.guild.id,
                message.channel.id,
                is_help=False,
                help_reply=lambda: send_notice(help_text(self.settings)),
                unwatched_reply=send_notice,
                unavailable_reply=send_notice,
                summarize=handle_request,
            )
            return
        await self.watch_gate.ingest(
            message.guild.id,
            message.channel.id,
            message,
            self.on_watched_message,
        )

    async def _read_usage(self) -> UsageSnapshot:
        if self.usage_reader is not None:
            return await self.usage_reader()
        if self.settings is None:
            raise UsageUnavailable("usage runtime is not configured")
        return await read_account_usage(
            self.settings.codex_executable,
            self.settings.codex_auth_directory / "auth.json",
            self.settings.input_directory.absolute(),
            client_version=__version__,
        )

    async def usage_reply(self) -> str:
        """Read usage one at a time, without touching the summary queue or cooldown."""
        async with self._usage_lock:
            try:
                snapshot = await self._read_usage()
            except UsageUnavailable:
                LOGGER.info("usage_request outcome=unavailable")
                return USAGE_UNAVAILABLE_NOTICE
        LOGGER.info("usage_request outcome=ok warning=%s", snapshot.warning)
        return usage_message(snapshot)

    async def status_reply(self, guild_id: int) -> str:
        """Report this Guild only, read-only, without the summary queue, model, or cooldown."""
        gateway_ready = self.ready_event.is_set()
        if self.settings is None:
            report = StatusReport(gateway_ready, None, None, None, None, None, False)
        else:
            report = await asyncio.to_thread(
                collect_status, self.settings, guild_id, gateway_ready=gateway_ready,
            )
        LOGGER.info("status_request healthy=%s", report.healthy)
        return status_message(report, self.clock())

    async def on_watched_message(self, message: discord.Message, lease: ChannelLease) -> None:
        """Persist eligible human messages only while the watch revision still matches."""
        if self.message_store is None:
            return
        assert message.guild is not None
        record = MessageRecord(
            message_id=message.id,
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            author_id=message.author.id,
            author_name=getattr(message.author, "display_name", None)
            or getattr(message.author, "name", "unknown"),
            content=message.content,
            created_at=message.created_at,
            edited_at=message.edited_at,
            has_attachment=bool(getattr(message, "attachments", ())),
            is_reply=message.type is discord.MessageType.reply,
        )
        try:
            if await asyncio.to_thread(
                self.message_store.upsert_if_watched,
                record,
                expected_version=lease.version,
                cached_at=self.clock(),
            ):
                LOGGER.info("message_cached")
        except MessageStoreError:
            LOGGER.warning("message_cache_write_failed")

    async def on_summary_request(
        self, message: discord.Message, request: RangeRequest, lease: ChannelLease,
        *, mode: SummaryMode = SummaryMode.NORMAL, scope: RangeScope | None = None,
    ) -> None:
        """Run the model path when the persistent runtime is configured."""
        LOGGER.info("summary_request_parsed kind=%s mode=%s", request.kind.value, mode.value)
        if (
            self.summary_workflow is None
            and self.settings is not None
            and isinstance(self.watch_store, SQLiteWatchStore)
            and self.message_store is not None
        ):
            try:
                self.summary_workflow = build_workflow(
                    self.settings, self, self.watch_store, self.message_store
                )
            except CodexContractError as exc:
                LOGGER.warning("summary_workflow_unavailable type=%s", type(exc).__name__)
                await message.channel.send(
                    UNAVAILABLE_NOTICE, allowed_mentions=discord.AllowedMentions.none()
                )
                return
        if self.summary_workflow is None:
            await message.channel.send(
                PREVIEW_NOTICE, allowed_mentions=discord.AllowedMentions.none()
            )
            return
        assert message.guild is not None

        async def send_notice(notice: str) -> None:
            await message.channel.send(notice, allowed_mentions=discord.AllowedMentions.none())

        await self.summary_workflow.run(
            SummaryRequest(
                message.guild.id, message.channel.id, message.author.id, request, mode, scope
            ),
            message.channel, lease, send_notice,
        )


async def run_gateway(
    settings: Settings,
    *,
    smoke_seconds: float | None = None,
    observe_channel_id: int | None = None,
) -> None:
    """Run the gateway; smoke mode closes after a bounded connection check."""
    with single_gateway(settings.input_directory):
        removed = cleanup_abandoned_workspaces(settings.input_directory)
        LOGGER.info("abandoned_requests_cleaned count=%d", removed)
        await _run_gateway_locked(
            settings, smoke_seconds=smoke_seconds, observe_channel_id=observe_channel_id
        )


async def _run_gateway_locked(
    settings: Settings,
    *,
    smoke_seconds: float | None,
    observe_channel_id: int | None,
) -> None:
    client = YoYackClient(
        observe_channel_id=observe_channel_id,
        watch_store=SQLiteWatchStore(settings.database_path),
        message_store=SQLiteMessageStore(settings.database_path),
        dev_guild_id=settings.dev_guild_id,
        settings=settings,
    )
    async with client:
        if smoke_seconds is None:
            await _serve_until_stop(client, settings.discord_bot_token)
            return
        task = asyncio.create_task(client.start(settings.discord_bot_token))
        try:
            ready = asyncio.create_task(client.ready_event.wait())
            done, _ = await asyncio.wait({ready, task}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
            if ready not in done:
                raise TimeoutError("Gateway did not become ready")
            await asyncio.sleep(smoke_seconds)
            LOGGER.info(
                "gateway_smoke_ok accepted_events=%d nonempty_content_events=%d",
                client.accepted_events,
                client.nonempty_content_events,
            )
        finally:
            ready.cancel()
            await client.close()
            if not task.done():
                task.cancel()
            await asyncio.gather(ready, task, return_exceptions=True)


async def _serve_until_stop(client: YoYackClient, token: str) -> None:
    """Drain accepted work on a normal service stop; crashes are recovered on restart."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    registered: list[signal.Signals] = []
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
            registered.append(signum)
        except NotImplementedError:
            pass
    running = asyncio.create_task(client.start(token))
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({running, stopping}, return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            await client.close()
        if running in done:
            await running
    finally:
        for signum in registered:
            loop.remove_signal_handler(signum)
        stopping.cancel()
        if not running.done():
            running.cancel()
        await asyncio.gather(stopping, running, return_exceptions=True)
