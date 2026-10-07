"""Discord Gateway entry point and conservative message boundary."""

import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol

import discord
from discord import app_commands

from yoyackbot import __version__, idiom, timing
from yoyackbot.backfill import (
    NOT_READY_NOTICE,
    BackfillError,
    BackfillNotifier,
    BackfillPageScheduler,
    BackfillState,
    CollectionProgress,
    InitialBackfill,
    RetryHolds,
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
from yoyackbot.channel_list import deliver_channel_list
from yoyackbot.codex import CodexContractError
from yoyackbot.collection_status import (
    CollectionStage,
    collection_lines,
    collection_stage,
    not_ready_detail,
)
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, SummaryMode, SummaryRequest
from yoyackbot.execution import SQLiteExecutionStore
from yoyackbot.execution_config import install_execution_settings
from yoyackbot.execution_log import log_message, timeout_event
from yoyackbot.health import COLLECTION_OK, write_heartbeat
from yoyackbot.help_command import install_help_command
from yoyackbot.idiom_command import install_idiom_command
from yoyackbot.input_files import cleanup_abandoned_workspaces, single_gateway
from yoyackbot.manager_roles import (
    ManagerRoleStore,
    MemoryManagerRoleStore,
    SQLiteManagerRoleStore,
)
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.parser import (
    HELP_MOVED_NOTICE,
    CommandLimitError,
    CommandSyntaxError,
    RouteKind,
    help_text,
    parse_summary_command,
    route_trigger,
)
from yoyackbot.range_request import resolve_range
from yoyackbot.reply_range import ReplyRangeRefused, reply_reference, resolve_reply_range
from yoyackbot.reply_refs import reply_target
from yoyackbot.role_config import install_role_commands
from yoyackbot.scope import RangeScope, describe_range
from yoyackbot.speed import SQLiteSpeedStore
from yoyackbot.speed_config import install_speed_command
from yoyackbot.status_report import StatusReport, collect_status, status_message
from yoyackbot.tone import SQLiteToneStore
from yoyackbot.tone_config import install_tone_command
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
EXECUTION_MATCH_SECONDS = 120  # /처형 call → its audit log entry
# A loop that survived this long starts its restart backoff from the beginning again.
WORKER_STABLE_SECONDS = 300
# One pass handles at most 20 channels, each page or notice bounded by 60 seconds.
WORKER_STALL_SECONDS = 900
PREVIEW_NOTICE = "🚧 요약 요청을 해석했소. 실제 요약 기능은 아직 준비 중이오. 🛠️"


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
    """Request only guild, guild-message, message-content and (1.4.0) audit-log events."""
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True
    intents.moderation = True  # audit log entries for the 처형 log (not a privileged intent)
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
        manager_roles: ManagerRoleStore | None = None,
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
        self.manager_roles: ManagerRoleStore = manager_roles or (
            SQLiteManagerRoleStore(settings.database_path)
            if settings is not None and isinstance(self.watch_store, SQLiteWatchStore)
            else MemoryManagerRoleStore()
        )
        self.dev_guild_id = dev_guild_id
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        if self.message_store is not None:
            self.message_store.clock = self.clock
            if settings is not None:
                self.message_store.retention_days = settings.cache_retention_days
        self.summary_workflow = summary_workflow
        self.usage_reader = usage_reader
        self._usage_lock = asyncio.Lock()
        self.backfill_store = (
            SQLiteBackfillStore(
                settings.database_path, retention_days=settings.cache_retention_days,
                clock=self.clock,
            )
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
        self.backfill_holds = RetryHolds()
        self.backfill_retry_seconds: tuple[float, float] = (5, 60)
        self.backfill_restart_seconds: tuple[float, float] = (1, 60)
        self.collection_worker = "starting"
        self.collection_restarts = 0
        self._collection_tick = time.monotonic()
        self._backfill_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._disconnected_at: datetime | None = None
        self._cache_recheck_pending = False
        self._connection_generation = 0
        self._synced_guild_ids: set[int] = set()
        self.tree = app_commands.CommandTree(self)
        self.executions: SQLiteExecutionStore | None = None
        # (guild, target) -> (caller, expiry): a /처형 the bot ran, credited to its caller (1.4.0)
        self._execution_callers: dict[tuple[int, int], tuple[int, float]] = {}
        install_channel_commands(self.tree, self.watch_store, self.manager_roles)
        install_role_commands(self.tree, self.manager_roles)
        install_help_command(self.tree, settings)
        install_idiom_command(self.tree, self._on_idiom_slash)
        if settings is not None and isinstance(self.watch_store, SQLiteWatchStore):
            install_tone_command(
                self.tree, SQLiteToneStore(settings.database_path), self.manager_roles,
            )
            install_speed_command(
                self.tree, SQLiteSpeedStore(settings.database_path), self.manager_roles,
            )
            self.executions = SQLiteExecutionStore(settings.database_path)
            install_execution_settings(self.tree, self.executions, self.manager_roles)

    async def setup_hook(self) -> None:
        if self.settings is not None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self.message_store is not None and self.settings is not None:
            await self._prune_once()
            if self.backfill_store is None:
                await self._mark_recheck("startup")
            self._cleanup_task = asyncio.create_task(self._prune_loop())
        if self.backfill_store is not None:
            seeded = await asyncio.to_thread(self.backfill_store.ensure_existing)
            LOGGER.info("initial_backfill_seeded count=%d", seeded)
            self._cache_recheck_pending = True
            await self._schedule_backfill_gap(self.clock())
            self._backfill_task = asyncio.create_task(self._supervise_backfill())
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
        generation = self._connection_generation
        self.connection_count += 1
        await self._resume_accessible_backfills()
        if self._disconnected_at is not None or self._cache_recheck_pending:
            await self._schedule_backfill_gap(self._disconnected_at or self.clock())
        if generation == self._connection_generation:
            self.ready_event.set()
        self._write_heartbeat()
        LOGGER.info("gateway_ready guild_count=%d", len(self.guilds))
        if self.executions is not None and self.guilds:
            try:  # settings of servers left while an older release ran (1.4.0)
                removed = await asyncio.to_thread(
                    self.executions.keep_only, [guild.id for guild in self.guilds],
                )
                if removed:
                    LOGGER.info("execution_settings_pruned count=%d", removed)
            except Exception:  # noqa: BLE001
                LOGGER.warning("execution_settings_prune_failed")
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
        generation = self._connection_generation
        LOGGER.info("gateway_resumed")
        await self._resume_accessible_backfills()
        if self._disconnected_at is not None or self._cache_recheck_pending:
            await self._schedule_backfill_gap(self._disconnected_at or self.clock())
        if generation == self._connection_generation:
            self.ready_event.set()
        self._write_heartbeat()

    async def on_disconnect(self) -> None:
        self._connection_generation += 1
        LOGGER.info("gateway_disconnected")
        self.ready_event.clear()
        self._write_heartbeat()
        self._disconnected_at = self._disconnected_at or self.clock()
        self._cache_recheck_pending = True

    def cache_available(self) -> bool:
        """A failed gap reservation or an active disconnect cannot allow summaries."""
        return not self._cache_recheck_pending and self._disconnected_at is None

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
                write_heartbeat(
                    self.settings.input_directory, gateway_ready=self.ready_event.is_set(),
                    collection_worker=self.collection_worker_state(),
                )
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

    async def _mark_recheck(self, reason: str) -> bool:
        if self.message_store is None or self.settings is None:
            return True
        end = self.clock()
        start = end - timedelta(days=self.settings.cache_retention_days)
        try:
            count = await asyncio.to_thread(
                self.message_store.mark_all_watched_recheck, start, end, reason=reason
            )
            LOGGER.info("cache_recheck_marked count=%d reason=%s", count, reason)
        except MessageStoreError:
            LOGGER.warning("cache_recheck_mark_failed")
            return False
        return True

    async def _schedule_backfill_gap(self, disconnected_at: datetime) -> bool:
        self._cache_recheck_pending = True
        generation = self._connection_generation
        if self.backfill_store is None:
            if not await self._mark_recheck("gateway_gap"):
                return False
            if generation != self._connection_generation:
                return False
            self._cache_recheck_pending = False
            self._disconnected_at = None
            return True
        try:
            count = await asyncio.to_thread(
                self.backfill_store.schedule_ready_recheck,
                start=disconnected_at, end=self.clock(),
            )
            LOGGER.info("backfill_gap_scheduled count=%d", count)
        except BackfillError:
            LOGGER.warning("backfill_gap_schedule_failed")
            return False
        if generation != self._connection_generation:
            return False
        self._cache_recheck_pending = False
        self._disconnected_at = None
        return True

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

    async def _supervise_backfill(self) -> None:
        """Restart the collection loop after an unexpected exit; cancellation ends it."""
        failures = 0
        while True:
            started = time.monotonic()
            try:
                await self._backfill_loop()
                raise RuntimeError("Collection loop returned")
            except asyncio.CancelledError:
                self.collection_worker = "stopped"
                raise
            except Exception:  # noqa: BLE001 - a defect must not silently end collection
                if time.monotonic() - started >= WORKER_STABLE_SECONDS:
                    failures = 0
                failures += 1
                self.collection_worker = "restarting"
                self.collection_restarts += 1
                LOGGER.warning("backfill_worker_restarting failures=%d", failures)
                self._write_heartbeat()
                first, cap = self.backfill_restart_seconds
                await asyncio.sleep(min(cap, first * 2 ** min(failures - 1, 16)))

    def collection_worker_state(self) -> str:
        """Report what the worker is doing; a live Gateway alone never means collecting."""
        if self.backfill_store is None:
            return "disabled"
        task = self._backfill_task
        if task is None:
            return "stopped"
        if task.done():
            return "failed"
        if (
            self.collection_worker == "running"
            and time.monotonic() - self._collection_tick > WORKER_STALL_SECONDS
        ):
            return "stalled"
        return self.collection_worker

    async def _backfill_loop(self) -> None:
        assert self.backfill_store is not None and self.initial_backfill is not None
        assert self.backfill_notifier is not None and self.backfill_scheduler is not None
        failures = 0
        while True:
            if not self.ready_event.is_set():
                self.collection_worker = "waiting"
                await self.ready_event.wait()
            self.collection_worker = "running"
            self._collection_tick = time.monotonic()
            if self._cache_recheck_pending and not await self._schedule_backfill_gap(
                self._disconnected_at or self.clock()
            ):
                failures += 1
                await self._loop_backoff(failures)
                continue
            try:
                pending = await asyncio.to_thread(self.backfill_store.pending, self.clock())
            except BackfillError:
                LOGGER.warning("initial_backfill_state_unavailable")
                failures += 1
                await self._loop_backoff(failures)
                continue
            failures = 0
            now = self.clock()
            runnable = [
                state for state in round_robin_backfills(pending)
                if not self.backfill_holds.held(state, now)
            ]
            results = await asyncio.gather(
                *(self._backfill_one(state) for state in runnable), return_exceptions=True,
            )
            for result in results:
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, BaseException):
                    # Isolated to that channel; the exception text may carry message data.
                    LOGGER.warning("initial_backfill_channel_failed kind=unexpected")
            if runnable:
                await asyncio.sleep(0.05)
            else:
                held = self.backfill_holds.wait_seconds(self.clock())
                await asyncio.sleep(3 if held is None else min(3, max(0.05, held)))

    async def _loop_backoff(self, failures: int) -> None:
        """Bounded wait while the shared collection state cannot be read or reserved."""
        self.collection_worker = "backoff"
        self._write_heartbeat()
        first, cap = self.backfill_retry_seconds
        await asyncio.sleep(min(cap, first * 2 ** min(failures - 1, 16)))

    async def _retry_backfill_later(self, state: BackfillState, delay: timedelta) -> None:
        """Persist the retry time; if even that fails, hold the channel in memory."""
        assert self.backfill_store is not None
        try:
            await asyncio.to_thread(self.backfill_store.defer, state, until=self.clock() + delay)
        except BackfillError:
            self.backfill_holds.fail(state, self.clock())
            LOGGER.warning("initial_backfill_state_write_failed action=defer")
            return
        self.backfill_holds.clear(state)

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
                await self._retry_backfill_later(state, timedelta(minutes=1))
                return False
            try:
                if state.first_watch and state.started_notice_id is None and not state.ready:
                    done = await asyncio.wait_for(
                        self.backfill_notifier.ensure(channel, state, ready=False), timeout=60,
                    )
                elif state.ready and state.first_watch and state.ready_notice_id is None:
                    done = await asyncio.wait_for(
                        self.backfill_notifier.ensure(channel, state, ready=True), timeout=60,
                    )
                elif state.ready:
                    done = True
                else:
                    done = await asyncio.wait_for(
                        self.initial_backfill.step(
                            channel, state,
                            can_continue=lambda: valid_channel(channel.guild, channel.id),
                        ), timeout=60,
                    )
                self.backfill_holds.clear(state)
                return done
            except BackfillError as exc:
                if not exc.retryable:
                    LOGGER.warning("initial_backfill_blocked kind=%s", exc.kind)
                    try:
                        await asyncio.to_thread(
                            self.backfill_store.block, state, reason=exc.kind
                        )
                    except BackfillError:
                        self.backfill_holds.fail(state, self.clock())
                        LOGGER.warning("initial_backfill_state_write_failed action=block")
                        return False
                    self.backfill_holds.clear(state)
                    return False
                LOGGER.warning("initial_backfill_page_deferred")
            except (MessageStoreError, TimeoutError):
                LOGGER.warning("initial_backfill_page_deferred")
            except Exception:  # noqa: BLE001 - one channel's defect must not stop the others
                LOGGER.warning("initial_backfill_page_failed kind=unexpected")
            await self._retry_backfill_later(state, timedelta(seconds=30))
            return False

        return await self.backfill_scheduler.run(state.guild_id, process)

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        try:
            if await asyncio.to_thread(self.watch_store.remove_channel, channel.guild.id, channel.id):
                LOGGER.info("watched_channel_deleted")
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_delete_cleanup_failed")
        if self.executions is not None:
            try:
                if await asyncio.to_thread(self.executions.remove_channel, channel.guild.id, channel.id):
                    LOGGER.info("execution_channel_deleted")
            except Exception:  # noqa: BLE001
                LOGGER.warning("execution_channel_cleanup_failed")

    def remember_execution(self, guild_id: int, target_id: int, caller_id: int) -> None:
        """`/처형` is about to time out `target_id`; its audit entry names the bot, not the caller."""
        now = time.monotonic()
        self._execution_callers = {
            key: value for key, value in self._execution_callers.items() if value[1] > now
        }
        self._execution_callers[guild_id, target_id] = caller_id, now + EXECUTION_MATCH_SECONDS

    def _execution_caller(self, guild_id: int, target_id: int) -> int | None:
        found = self._execution_callers.pop((guild_id, target_id), None)
        return found[0] if found is not None and found[1] > time.monotonic() else None

    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """1.4.0: post timeouts applied, extended or lifted to the server's 처형 log channel."""
        event = timeout_event(entry)
        guild = getattr(entry, "guild", None)
        if event is None or guild is None or self.executions is None:
            return
        executor = event.executor_id
        by_command = False
        if self.user is not None and executor == self.user.id:
            caller = self._execution_caller(guild.id, event.target_id)
            if caller is not None:
                executor, by_command = caller, True
        try:
            channel_id = await asyncio.to_thread(self.executions.log_channel, guild.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("execution_log_settings_unreadable")
            return
        if channel_id is None:
            return
        channel = guild.get_channel(channel_id)
        if channel is None or not valid_channel(guild, channel_id):
            LOGGER.warning("execution_log_channel_unavailable")
            return
        try:
            await channel.send(
                log_message(event, executor), allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.DiscordException, OSError):
            LOGGER.warning("execution_log_post_failed")
            return
        LOGGER.info("execution_logged kind=%s by_command=%s", event.kind, by_command)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        try:
            await asyncio.to_thread(self.watch_store.remove_guild, guild.id)
            LOGGER.info("watched_guild_removed")
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_guild_cleanup_failed")
        try:
            await asyncio.to_thread(self.manager_roles.remove_guild, guild.id)
        except Exception:  # noqa: BLE001
            LOGGER.warning("manager_roles_cleanup_failed")

    async def on_guild_role_delete(self, role: discord.Role) -> None:
        try:
            if await asyncio.to_thread(self.manager_roles.remove_role, role.guild.id, role.id):
                LOGGER.info("manager_role_deleted")
        except Exception:  # noqa: BLE001
            LOGGER.warning("manager_role_cleanup_failed")
        if self.executions is not None:
            try:
                if await asyncio.to_thread(self.executions.remove_role, role.guild.id, role.id):
                    LOGGER.info("execution_role_deleted")
            except Exception:  # noqa: BLE001
                LOGGER.warning("execution_role_cleanup_failed")

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if classify_message(after) is not MessageClass.HUMAN_TEXT or after.guild is None:
            return
        if self.message_store is not None and after.edited_at is None:
            if getattr(before, "content", None) == after.content:
                return
            try:
                await asyncio.to_thread(
                    self.message_store.update_content,
                    after.guild.id, after.channel.id, after.id, after.content,
                    edited_at=None, cached_at=self.clock(),
                )
            except MessageStoreError:
                LOGGER.warning("message_edit_sync_failed")
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
            edited_at = datetime.fromisoformat(raw_edited) if isinstance(raw_edited, str) else None
        except ValueError:
            edited_at = None
        if edited_at is not None and edited_at.tzinfo is None:
            edited_at = None
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
        if route.kind in (RouteKind.SUMMARY, RouteKind.IDIOM):
            timing.begin(getattr(message, "created_at", None))  # 0 ms of `request_timing`
        if route.kind is RouteKind.HELP:
            LOGGER.info("help_request surface=text")
            await message.channel.send(
                HELP_MOVED_NOTICE, allowed_mentions=discord.AllowedMentions.none()
            )
            return
        assert message.guild is not None
        if route.kind in (RouteKind.USAGE, RouteKind.STATUS, RouteKind.CHANNELS):
            async def send_usage(notice: str) -> None:
                await message.channel.send(
                    notice, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=True,
                )

            async def handle_usage(_lease: ChannelLease) -> None:
                if route.kind is RouteKind.USAGE:
                    await send_usage(await self.usage_reply())
                elif route.kind is RouteKind.STATUS:
                    await send_usage(await self.status_reply(message.guild.id, message.channel.id))
                else:
                    limit = self.settings.discord_message_limit if self.settings else 1900
                    await send_usage(await deliver_channel_list(
                        message.guild, message.author, self.watch_store,
                        origin_channel_id=message.channel.id, limit=limit,
                    ))

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
        if route.kind in (RouteKind.IDIOM, RouteKind.IDIOM_USAGE):
            await self._on_idiom(message, usage=route.kind is RouteKind.IDIOM_USAGE)
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
                        backfill, _generation, pending = await asyncio.to_thread(
                            self.backfill_store.readiness_snapshot,
                            message.guild.id, message.channel.id,
                            cutoff=self.clock() - timedelta(days=self.settings.cache_retention_days),
                        )
                    except BackfillError:
                        await send_notice(UNAVAILABLE_NOTICE)
                        return
                    if not self.cache_available() or pending or not summary_ready(backfill):
                        await send_notice(await self._not_ready_notice(
                            message.guild.id, message.channel.id,
                        ))
                        return
                reference = reply_reference(message)
                try:
                    command = parse_summary_command(route.options)
                    range_text, mode = command.range_text, command.mode
                    if reference is not None:
                        # A reply sets the start; a range written with it is ignored (1.3.0).
                        request, scope = await resolve_reply_range(
                            message, reference, store=self.message_store,
                            settings=self.settings, accepted_at=accepted_at,
                            ignored_range=bool(range_text),
                        )
                    else:
                        scope = describe_range(range_text, self.settings)
                        request = resolve_range(
                            range_text,
                            self.settings,
                            accepted_at,
                            trigger_message_id=getattr(message, "id", None),
                        )
                except (CommandSyntaxError, CommandLimitError, ReplyRangeRefused) as exc:
                    await send_notice(str(exc))
                    return
                except MessageStoreError:
                    await send_notice(UNAVAILABLE_NOTICE)
                    return
                await self.on_summary_request(
                    message, request, lease, mode=mode, scope=scope, note=command.note,
                )

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

    async def _on_idiom(self, message: discord.Message, *, usage: bool) -> None:
        """`!!말하자면` (1.3.0): fixed casual notices; a reply never changes its range."""
        assert message.guild is not None

        async def send(notice: str) -> None:
            await message.channel.send(notice, allowed_mentions=discord.AllowedMentions.none())

        await self._idiom_request(
            message.guild, message.channel, send, accepted_at=self.clock(),
            trigger_message_id=getattr(message, "id", None), usage=usage, surface="text",
        )

    async def _on_idiom_slash(self, interaction: discord.Interaction) -> None:
        """`/말하자면` (1.3.4): only the caller sees the command and any notice; the answer is a
        plain channel message, so it pops up with no visible set-up."""
        timing.begin(getattr(interaction, "created_at", None))
        accepted_at = self.clock()
        await interaction.response.defer(ephemeral=True, thinking=True)
        noticed: list[str] = []

        async def send(notice: str) -> None:
            noticed.append(notice)
            try:
                await interaction.edit_original_response(content=notice)
            except discord.HTTPException:
                LOGGER.warning("idiom_slash_notice_failed")

        guild, channel = interaction.guild, interaction.channel
        if guild is None or channel is None:
            await send(idiom.UNWATCHED_NOTICE)
            return
        outcome = await self._idiom_request(
            guild, channel, send, accepted_at=accepted_at, trigger_message_id=None,
            usage=False, surface="slash",
        )
        if outcome == "success":
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                LOGGER.warning("idiom_slash_cleanup_failed")
        elif not noticed:
            await send(idiom.FAILED_NOTICE)

    async def _idiom_request(
        self, guild: discord.Guild, channel: discord.abc.Messageable,
        send: Callable[[str], Awaitable[None]], *, accepted_at: datetime,
        trigger_message_id: int | None, usage: bool, surface: str,
    ) -> str | None:
        """The shared `!!말하자면`/`/말하자면` path; returns the workflow outcome, if it ran."""
        outcome: str | None = None

        async def handle(lease: ChannelLease) -> None:
            nonlocal outcome
            if usage:
                await send(idiom.USAGE_NOTICE)
                return
            if (
                self.settings is None or self.message_store is None
                or not isinstance(self.watch_store, SQLiteWatchStore)
            ):
                await send(idiom.UNAVAILABLE_NOTICE)
                return
            if self.summary_workflow is None:
                try:
                    self.summary_workflow = build_workflow(
                        self.settings, self, self.watch_store, self.message_store,
                    )
                except CodexContractError:
                    LOGGER.warning("summary_workflow_unavailable type=CodexContractError")
                    await send(idiom.FAILED_NOTICE)
                    return
            if self.backfill_store is not None:
                try:
                    backfill, _generation, pending = await asyncio.to_thread(
                        self.backfill_store.readiness_snapshot,
                        guild.id, channel.id,
                        cutoff=self.clock() - timedelta(days=self.settings.cache_retention_days),
                    )
                except BackfillError:
                    await send(idiom.UNAVAILABLE_NOTICE)
                    return
                if not self.cache_available() or pending or not summary_ready(backfill):
                    await send(idiom.NOT_READY_NOTICE)
                    return
            LOGGER.info("idiom_request_parsed surface=%s", surface)
            outcome = await self.summary_workflow.run_idiom(
                guild.id, channel, lease, send, accepted_at=accepted_at,
                trigger_message_id=trigger_message_id, surface=surface,
            )

        await self.watch_gate.request(
            guild.id, channel.id, is_help=False,
            help_reply=lambda: send(idiom.USAGE_NOTICE),
            unwatched_reply=lambda _notice: send(idiom.UNWATCHED_NOTICE),
            unavailable_reply=lambda _notice: send(idiom.UNAVAILABLE_NOTICE),
            summarize=handle,
        )
        return outcome

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

    async def _collection_progress(
        self, guild_id: int, channel_id: int,
    ) -> CollectionProgress | None:
        """This channel's progress, or None when it cannot be read (shown as unknown)."""
        if self.backfill_store is None or self.settings is None:
            return None
        try:
            return await asyncio.to_thread(
                self.backfill_store.progress_snapshot, guild_id, channel_id,
                cutoff=self.clock() - timedelta(days=self.settings.cache_retention_days),
            )
        except BackfillError:
            LOGGER.warning("collection_progress_unavailable")
            return None

    async def _not_ready_notice(self, guild_id: int, channel_id: int) -> str:
        progress = await self._collection_progress(guild_id, channel_id)
        stage = collection_stage(progress, now=self.clock(), cache_available=self.cache_available())
        if stage is CollectionStage.READY:
            return NOT_READY_NOTICE  # it became ready between the two reads
        detail = not_ready_detail(
            progress, now=self.clock(), cache_available=self.cache_available(),
            worker=self.collection_worker_state(),
        )
        return f"{NOT_READY_NOTICE}\n{detail}"

    async def status_reply(self, guild_id: int, channel_id: int | None = None) -> str:
        """Report this Guild and the asking channel only, without the queue, model, or cooldown."""
        gateway_ready = self.ready_event.is_set()
        worker = self.collection_worker_state()
        collecting = worker in COLLECTION_OK
        if self.settings is None:
            report = StatusReport(gateway_ready, None, None, None, None, None, False, collecting)
        else:
            report = await asyncio.to_thread(
                collect_status, self.settings, guild_id, gateway_ready=gateway_ready,
                collection_ok=collecting,
            )
        text = status_message(report, self.clock())
        stage = "none"
        if channel_id is not None and self.backfill_store is not None:
            progress = await self._collection_progress(guild_id, channel_id)
            stage = collection_stage(
                progress, now=self.clock(), cache_available=self.cache_available(),
            ).value
            text += "\n\n" + "\n".join(collection_lines(
                progress, now=self.clock(), cache_available=self.cache_available(),
                worker=worker,
            ))
        LOGGER.info("status_request healthy=%s collection_stage=%s", report.healthy, stage)
        return text

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
            reply_to_message_id=reply_target(message, message.guild.id, message.channel.id),
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
        *, mode: SummaryMode = SummaryMode.SHORT, scope: RangeScope | None = None,
        note: str | None = None,
    ) -> None:
        """Run the model path when the persistent runtime is configured."""
        LOGGER.info(
            "summary_request_parsed kind=%s mode=%s reply=%s has_request=%s request_chars=%d",
            request.kind.value, mode.value, request.anchor_message_id is not None,
            note is not None, len(note or ""),
        )
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
                message.guild.id, message.channel.id, message.author.id, request, mode, scope,
                note,
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
