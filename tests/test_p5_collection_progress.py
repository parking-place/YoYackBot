"""F02: the current channel's collection stage, page progress, and its storage (T120-P5-A..D)."""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.backfill import (
    NOT_READY_NOTICE,
    BackfillError,
    InitialBackfill,
    SQLiteBackfillStore,
    summary_ready,
)
from yoyackbot.collection_status import (
    BLOCK_REASON,
    STAGE_TEXT,
    UNKNOWN,
    WORKER_STOPPED,
    CollectionStage,
    collection_lines,
    collection_stage,
    not_ready_detail,
)
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import MessageRecord
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.settings_backup import backup_settings
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
SECRET = "합성 비밀 원문"


def message(when: datetime, number: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=discord.utils.time_snowflake(when) + number, created_at=when, edited_at=None,
        guild=SimpleNamespace(id=1), channel=SimpleNamespace(id=99),
        author=SimpleNamespace(id=7, display_name="합성 화자", bot=False), webhook_id=None,
        content=SECRET, type=discord.MessageType.default, attachments=(),
    )


class Pages:
    def __init__(self, items=()) -> None:
        self.items = list(items)
        self.failure = False

    async def fetch_page(self, channel, *, before: int, limit: int, after: int | None = None):
        if self.failure:
            raise OSError("synthetic History interruption")
        return sorted(
            (item for item in self.items if (after or 0) < item.id < before),
            key=lambda item: item.id, reverse=True,
        )[:limit]


def setup(tmp_path: Path):
    now = [NOW]
    path = tmp_path / "messages.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99, 98}))
    store = SQLiteBackfillStore(path, clock=lambda: now[0])
    messages = SQLiteMessageStore(path, clock=lambda: now[0])
    channel = SimpleNamespace(id=99, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)
    source = Pages([message(NOW - timedelta(hours=hour), hour) for hour in range(1, 6)])
    worker = InitialBackfill(store, source, clock=lambda: now[0], page_size=2)
    return SimpleNamespace(now=now, path=path, watches=watches, store=store, messages=messages,
                           channel=channel, source=source, worker=worker)


def snapshot(context, channel_id: int = 99):
    return context.store.progress_snapshot(1, channel_id, cutoff=context.now[0] - timedelta(days=30))


def step(context) -> bool:
    state = context.store.get(1, 99)
    return asyncio.run(context.worker.step(context.channel, state))


def sql(context, statement: str, *args) -> None:
    with sqlite3.connect(context.path) as connection:
        connection.execute(statement, args)


# T120-P5-B ------------------------------------------------------------------------------

def test_pages_count_only_committed_pages_of_the_current_run(tmp_path) -> None:
    context = setup(tmp_path)
    first = snapshot(context)
    assert (first.pages, first.last_progress, first.stored_messages) == (0, None, 0)
    context.now[0] += timedelta(seconds=10)
    assert step(context)
    after_one = snapshot(context)
    assert after_one.pages == 1 and after_one.last_progress == context.now[0]
    assert after_one.stored_messages == 2

    # A failed History fetch commits nothing and counts nothing.
    context.source.failure = True
    with pytest.raises(BackfillError):
        step(context)
    context.source.failure = False
    assert snapshot(context).pages == 1

    # Replaying a stale state (same page again) is rejected without counting.
    stale = context.store.get(1, 99)
    assert step(context)
    assert not asyncio.run(context.worker.step(context.channel, stale))
    assert snapshot(context).pages == 2

    # A rolled-back page commit leaves the counter and cursor untouched.
    before = context.store.get(1, 99)

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("synthetic disk failure")

    original = SQLiteMessageStore._reconcile_page
    SQLiteMessageStore._reconcile_page = staticmethod(broken)
    try:
        with pytest.raises(BackfillError):
            step(context)
    finally:
        SQLiteMessageStore._reconcile_page = original
    assert context.store.get(1, 99) == before and snapshot(context).pages == 2

    # A live message changes the stored count, not the page count.
    context.messages.upsert(MessageRecord(10**18, 1, 99, 7, "합성 화자", SECRET, NOW), cached_at=NOW)
    assert snapshot(context).stored_messages == 5 and snapshot(context).pages == 2

    # Restarting the store keeps counting the same run.
    context.store = SQLiteBackfillStore(context.path, clock=lambda: context.now[0])
    context.worker = InitialBackfill(context.store, context.source, clock=lambda: context.now[0],
                                     page_size=2)
    while context.store.get(1, 99).phase != "ready":
        step(context)
    done = snapshot(context)
    assert done.state.phase == "ready" and done.pages is not None and done.pages >= 4


def test_new_gap_run_restarts_the_count_and_old_tokens_never_count(tmp_path) -> None:
    context = setup(tmp_path)
    while context.store.get(1, 99).phase != "ready":
        step(context)
    finished = snapshot(context).pages
    context.now[0] += timedelta(minutes=5)
    context.store.schedule_ready_recheck(end=context.now[0], start=context.now[0] - timedelta(minutes=5))
    gap = snapshot(context)
    assert finished and gap.pages == 0 and gap.recheck_pending and gap.state.phase == "history"
    with sqlite3.connect(context.path) as connection:
        assert connection.execute("SELECT kind FROM backfill_progress WHERE channel_id=99").fetchone() == (
            "recheck",
        )
    old = context.store.get(1, 99)
    context.watches.replace(1, frozenset({98}))
    context.watches.replace(1, frozenset({98, 99}))
    assert not asyncio.run(context.worker.step(context.channel, old))
    renewed = snapshot(context)
    assert renewed.state.token != old.token and renewed.pages == 0


def test_a_page_from_a_writer_that_does_not_count_makes_the_run_unknown(tmp_path) -> None:
    context = setup(tmp_path)
    assert step(context)
    # An older release advances the cursor without touching backfill_progress.
    sql(context, "UPDATE backfill_state SET before_id=before_id-1000 WHERE channel_id=99")
    assert snapshot(context).pages is None
    assert step(context)
    assert snapshot(context).pages is None and snapshot(context).last_progress is None


# T120-P5-A ------------------------------------------------------------------------------

def stage_of(context, *, cache_available: bool = True) -> CollectionStage:
    return collection_stage(snapshot(context), now=context.now[0], cache_available=cache_available)


def test_every_stage_matches_whether_a_summary_may_run(tmp_path) -> None:
    context = setup(tmp_path)
    assert stage_of(context) is CollectionStage.INITIAL
    sql(context, "UPDATE backfill_state SET retry_at_us=? WHERE channel_id=99",
        int((NOW + timedelta(seconds=90)).timestamp() * 1_000_000))
    assert stage_of(context) is CollectionStage.RETRY
    lines = collection_lines(snapshot(context), now=NOW, cache_available=True, worker="running")
    assert "🔁 다음 재시도: 1분 뒤이오." in lines
    sql(context, "UPDATE backfill_state SET retry_at_us=0, blocked_reason='permission' WHERE channel_id=99")
    assert stage_of(context) is CollectionStage.BLOCKED
    assert BLOCK_REASON["permission"] in collection_lines(
        snapshot(context), now=NOW, cache_available=True, worker="running")
    sql(context, "UPDATE backfill_state SET blocked_reason=NULL WHERE channel_id=99")
    while context.store.get(1, 99).phase != "ready":
        step(context)
    # First watch: ready phase but the ready notice is not posted yet.
    assert stage_of(context) is CollectionStage.NOTICE
    assert not summary_ready(snapshot(context).state)
    sql(context, "UPDATE backfill_state SET ready_notice_id=5 WHERE channel_id=99")
    assert stage_of(context) is CollectionStage.READY
    assert stage_of(context, cache_available=False) is CollectionStage.GAP
    context.messages.mark_all_watched_recheck(NOW - timedelta(hours=1), NOW, reason="synthetic")
    assert stage_of(context) is CollectionStage.RECHECK
    for stage in CollectionStage:
        assert STAGE_TEXT[stage]


def test_stopped_worker_is_never_shown_as_collecting(tmp_path) -> None:
    context = setup(tmp_path)
    for worker, warned in [("running", False), ("waiting", False), ("restarting", True),
                           ("failed", True), ("stalled", True), (None, True)]:
        lines = collection_lines(snapshot(context), now=NOW, cache_available=True, worker=worker)
        assert (WORKER_STOPPED in lines) is warned
        assert (WORKER_STOPPED in not_ready_detail(
            snapshot(context), now=NOW, cache_available=True, worker=worker,
        )) is warned


def client_for(context) -> YoYackClient:
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(context.path),
        "YOYACK_INPUT_DIRECTORY": str(context.path.parent / "inputs"),
    })
    client = YoYackClient(
        watch_store=context.watches, message_store=context.messages, settings=settings,
        clock=lambda: context.now[0],
    )
    client.backfill_store = context.store
    return client


def test_status_and_not_ready_replies_describe_only_this_channel(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    context = setup(tmp_path)
    assert step(context)
    sql(context, "UPDATE backfill_state SET blocked_reason='channel_gone' WHERE channel_id=98")

    async def scenario():
        client = client_for(context)
        try:
            text = await client.status_reply(1, 99)
            notice = await client._not_ready_notice(1, 99)
            return text, notice
        finally:
            await client.close()

    text, notice = asyncio.run(scenario())
    assert "📍 이 채널 수집: 📥 처음 수집하는 중이오." in text
    assert "📄 이번 수집에서 처리한 쪽: 1쪽이오." in text
    assert "💬 이 채널에 저장된 대화: 2건이오." in text
    assert "🕒 마지막 진척: 방금 전이오." in text
    # The worker task was not started in this harness, so it is honestly reported as stopped.
    assert WORKER_STOPPED in text and "🩺 상태: 점검이 필요하오. 🚨" in text
    assert notice.startswith(NOT_READY_NOTICE + "\n📥 처음 수집하는 중이오.\n📄 처리 1쪽 · 💬 저장 2건")
    for reply in (text, notice):
        assert "98" not in reply and "채널을 찾을 수 없소" not in reply
        assert SECRET not in reply and "%" not in reply and "남은" not in reply
        assert str(context.path) not in reply
    assert SECRET not in caplog.text and str(context.path) not in caplog.text
    assert "collection_stage=initial" in caplog.text


# T120-P5-C ------------------------------------------------------------------------------

def test_unreadable_progress_is_unknown_not_zero(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    context = setup(tmp_path)

    class Broken(SQLiteBackfillStore):
        def progress_snapshot(self, *_args, **_kwargs):
            raise BackfillError(f"secret path {context.path}")

    async def scenario():
        client = client_for(context)
        client.backfill_store = Broken(context.path, clock=lambda: NOW)
        try:
            return await client.status_reply(1, 99), await client._not_ready_notice(1, 99)
        finally:
            await client.close()

    text, notice = asyncio.run(scenario())
    assert "📍 이 채널 수집: " + STAGE_TEXT[CollectionStage.UNKNOWN] in text
    assert "💬 저장된 대화: " + UNKNOWN in text and "0건" not in text.split("📍")[1]
    assert STAGE_TEXT[CollectionStage.UNKNOWN] in notice and "0건" not in notice
    assert "collection_progress_unavailable" in caplog.text and str(context.path) not in caplog.text


def test_unknown_pages_are_shown_as_unknown(tmp_path) -> None:
    context = setup(tmp_path)
    sql(context, "DELETE FROM backfill_progress")
    lines = collection_lines(snapshot(context), now=NOW, cache_available=True, worker="running")
    assert "📄 이번 수집에서 처리한 쪽: " + UNKNOWN in lines
    assert "🕒 마지막 진척: " + UNKNOWN in lines
    assert "📄 처리 확인 불가 · 💬 저장 0건" in not_ready_detail(
        snapshot(context), now=NOW, cache_available=True, worker="running")


# T120-P5-D ------------------------------------------------------------------------------

def test_upgrade_backup_cleanup_and_downgrade_reupgrade(tmp_path) -> None:
    context = setup(tmp_path)
    assert step(context)
    # An older release had no progress table at all.
    sql(context, "DROP TABLE backfill_progress")
    SQLiteWatchStore(context.path)
    with sqlite3.connect(context.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
        assert connection.execute("SELECT COUNT(*) FROM backfill_progress").fetchone() == (0,)
    assert snapshot(context).pages is None  # the upgraded run's earlier pages are not guessed

    backup = backup_settings(context.path, tmp_path / "backups")
    payload = json.loads(backup.read_text())
    assert "progress" not in json.dumps(sorted(payload)) and "backfill" not in json.dumps(sorted(payload))

    # Cleanup on unwatch, channel deletion, and Guild removal.
    context.watches.replace(1, frozenset({99, 98}))

    def count() -> int:
        with closing(sqlite3.connect(context.path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM backfill_progress").fetchone()[0]

    context.watches.replace(1, frozenset({99, 98, 97}))
    assert count() == 1  # only the new channel 97's run is counted from its start
    context.watches.replace(1, frozenset({99, 98}))
    assert count() == 0
    context.watches.replace(1, frozenset({99, 98, 96}))
    context.watches.remove_channel(1, 96)
    assert count() == 0
    context.watches.replace(1, frozenset({99, 98, 95}))
    context.watches.remove_guild(1)
    assert count() == 0

    # Downgrade: the older release unwatches without knowing the table; re-upgrade prunes it.
    context.watches.replace(1, frozenset({99}))
    assert count() == 1
    sql(context, "DELETE FROM watched_channels WHERE channel_id=99")
    sql(context, "DELETE FROM backfill_state WHERE channel_id=99")
    SQLiteWatchStore(context.path)
    assert count() == 0


def test_status_reply_without_a_channel_keeps_the_guild_view(tmp_path) -> None:
    context = setup(tmp_path)

    async def scenario():
        client = client_for(context)
        try:
            return await client.status_reply(1)
        finally:
            await client.close()

    assert "📍" not in asyncio.run(scenario())


def test_not_ready_gateway_path_uses_the_same_snapshot(tmp_path, monkeypatch) -> None:
    context = setup(tmp_path)
    assert step(context)

    async def scenario():
        client = client_for(context)
        channel = SimpleNamespace(id=99, type=discord.ChannelType.text, name="합성", send=AsyncMock())
        guild = SimpleNamespace(id=1, me=object(), get_channel=lambda _id: channel)
        channel.guild = guild
        monkeypatch.setattr("yoyackbot.watch_gate.valid_channel", lambda *_: True, raising=False)
        event = SimpleNamespace(
            id=10, guild=guild, channel=channel, content="!!요약좀",
            author=SimpleNamespace(id=7, bot=False), webhook_id=None,
            type=discord.MessageType.default,
        )
        try:
            await client.on_message(event)
            return channel.send.await_args.args[0]
        finally:
            await client.close()

    sent = asyncio.run(scenario())
    assert sent.startswith(NOT_READY_NOTICE + "\n📥 처음 수집하는 중이오.")
