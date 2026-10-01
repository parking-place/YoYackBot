"""Initial collection announcements survive uncertain sends and block early summaries."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.backfill import (
    NOT_READY_NOTICE,
    READY_NOTICE,
    START_NOTICE,
    BackfillError,
    BackfillNotifier,
    InitialBackfill,
    SQLiteBackfillStore,
)
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore


class FakeChannel:
    type = discord.ChannelType.text
    id = 99
    guild = SimpleNamespace(id=1)

    def __init__(self, clock) -> None:
        self.clock = clock
        self.sent: list[SimpleNamespace] = []
        self.fail_after_send = False

    async def send(self, content: str, **_kwargs) -> SimpleNamespace:
        message = SimpleNamespace(
            id=discord.utils.time_snowflake(self.clock()) + len(self.sent) + 1,
            content=content, author=SimpleNamespace(id=42),
        )
        self.sent.append(message)
        if self.fail_after_send:
            self.fail_after_send = False
            response = SimpleNamespace(status=500, reason="synthetic", headers={})
            raise discord.HTTPException(response, "synthetic")
        return message

    async def history(self, *, after, limit, oldest_first):
        assert oldest_first and limit == 100
        for message in self.sent:
            if message.id > after.id:
                yield message


class EmptyPages:
    async def fetch_page(self, *_args, **_kwargs):
        return []


def test_start_and_ready_notices_are_exact_and_once_per_new_watch(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({99}))
        store = SQLiteBackfillStore(path)
        state = store.get(1, 99)
        assert state is not None
        now = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=state.started_us)
        clock = lambda: now + timedelta(seconds=1)
        channel = FakeChannel(clock)
        notifier = BackfillNotifier(store, bot_user_id=lambda: 42, clock=clock)
        assert await notifier.ensure(channel, state, ready=False)
        assert await notifier.ensure(channel, state, ready=False)
        assert [item.content for item in channel.sent] == [START_NOTICE]

        worker = InitialBackfill(store, EmptyPages(), clock=clock)
        history = store.get(1, 99)
        assert history is not None
        assert await worker.step(channel, history)
        overlap = store.get(1, 99)
        assert overlap is not None and overlap.phase == "overlap"
        assert await worker.step(channel, overlap)
        ready = store.get(1, 99)
        assert ready is not None and ready.ready
        assert await notifier.ensure(channel, ready, ready=True)
        restarted = BackfillNotifier(store, bot_user_id=lambda: 42, clock=clock)
        assert await restarted.ensure(channel, ready, ready=True)
        assert [item.content for item in channel.sent] == [START_NOTICE, READY_NOTICE]

    asyncio.run(scenario())


def test_blocked_first_collection_never_announces_ready_before_recovery(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        SQLiteWatchStore(path).replace(1, frozenset({99}))
        store = SQLiteBackfillStore(path)
        state = store.get(1, 99)
        assert state is not None
        now = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=state.started_us)
        channel = FakeChannel(lambda: now + timedelta(seconds=1))
        notifier = BackfillNotifier(store, bot_user_id=lambda: 42,
                                    clock=lambda: now + timedelta(seconds=1))
        assert await notifier.ensure(channel, state, ready=False)
        assert store.block(state, reason="permission")
        blocked = store.get(1, 99)
        assert blocked is not None and blocked.blocked_reason == "permission"
        assert not await notifier.ensure(channel, blocked, ready=True)
        assert [item.content for item in channel.sent] == [START_NOTICE]

        assert store.resume_blocked(1, 99)
        worker = InitialBackfill(store, EmptyPages(), clock=lambda: now + timedelta(seconds=1))
        for _ in range(2):
            current = store.get(1, 99)
            assert current is not None and await worker.step(channel, current)
        ready = store.get(1, 99)
        assert ready is not None and ready.ready
        assert await notifier.ensure(channel, ready, ready=True)
        assert [item.content for item in channel.sent] == [START_NOTICE, READY_NOTICE]

    asyncio.run(scenario())


def test_ambiguous_send_is_found_before_retry(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        SQLiteWatchStore(path).replace(1, frozenset({99}))
        store = SQLiteBackfillStore(path)
        state = store.get(1, 99)
        assert state is not None
        now = datetime.now(UTC)
        channel = FakeChannel(lambda: now + timedelta(seconds=1))
        channel.fail_after_send = True
        notifier = BackfillNotifier(store, bot_user_id=lambda: 42, clock=lambda: now)
        with pytest.raises(BackfillError):
            await notifier.ensure(channel, state, ready=False)
        assert len(channel.sent) == 1
        assert store.get(1, 99).started_notice_attempt_us is not None  # type: ignore[union-attr]
        assert await notifier.ensure(channel, state, ready=False)
        assert len(channel.sent) == 1
        recorded = store.get(1, 99)
        assert recorded is not None and recorded.started_notice_id == channel.sent[0].id

    asyncio.run(scenario())


def test_migrated_watch_has_no_first_watch_announcement(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        SQLiteWatchStore(path).replace(1, frozenset({99}))
        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM backfill_state")
        store = SQLiteBackfillStore(path)
        assert store.ensure_existing() == 1
        migrated = store.get(1, 99)
        assert migrated is not None and not migrated.first_watch
        channel = FakeChannel(lambda: datetime.now(UTC))
        notifier = BackfillNotifier(store, bot_user_id=lambda: 42)
        assert await notifier.ensure(channel, migrated, ready=False)
        assert channel.sent == []

    asyncio.run(scenario())


def test_summary_waits_without_model_or_cooldown_while_help_remains_available(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({99}))
        settings = Settings.from_environment({
            "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path),
        })
        channel = FakeChannel(lambda: datetime.now(UTC))

        class UnusedWorkflow:
            calls = 0

            async def run(self, *_args, **_kwargs) -> None:
                self.calls += 1

            async def shutdown(self) -> None:
                pass

        workflow = UnusedWorkflow()
        client = YoYackClient(
            watch_store=watches, message_store=SQLiteMessageStore(path),
            settings=settings, summary_workflow=workflow,  # type: ignore[arg-type]
        )

        async def send_command(content: str) -> None:
            message = SimpleNamespace(
                guild=channel.guild, channel=channel,
                author=SimpleNamespace(id=7, bot=False), webhook_id=None,
                type=discord.MessageType.default, content=content,
            )
            await client.on_message(message)

        try:
            for command in ("!!요약좀", "!!요약좀 5분", "!!요약좀 100개"):
                await send_command(command)
            assert [item.content for item in channel.sent] == [NOT_READY_NOTICE] * 3
            assert workflow.calls == 0
            await send_command("!!요약좀 도움")
            assert "`30일` 지원" in channel.sent[-1].content
            assert workflow.calls == 0
        finally:
            await client.close()

    asyncio.run(scenario())
