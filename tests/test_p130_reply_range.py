"""1.3.0-P3: `!!요약좀` as a reply summarizes from the replied-to message (T130-P3-A/B)."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.backfill import SQLiteBackfillStore
from yoyackbot.cache_collector import CacheOnlyCollector
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryMode
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.parser import OptionKind
from yoyackbot.reply_range import (
    LOOKUP_FAILED_NOTICE,
    MISSING_NOTICE,
    OTHER_CHANNEL_NOTICE,
    too_many_notice,
    too_old_notice,
)
from yoyackbot.scope import REPLY_IGNORED_LINE, RangeScope, busy_notice, start_notice
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
BASE = discord.utils.time_snowflake(NOW - timedelta(hours=5))


def mid(n: int) -> int:
    return BASE + n * 1_000_000


def setup(tmp_path, **env):
    path = tmp_path / "db.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({2}))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, verified_us=?, "
            "finished_us=?", (int(NOW.timestamp() * 1_000_000),) * 3)
    messages = SQLiteMessageStore(path, clock=lambda: NOW)
    for n in range(1, 6):
        messages.upsert(MessageRecord(mid(n), 1, 2, 7, "가람", f"합성 {n}",
                                      NOW - timedelta(hours=4) + timedelta(minutes=n)), cached_at=NOW)
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path),
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"), **env,
    })
    client = YoYackClient(watch_store=watches, message_store=messages, settings=settings,
                          clock=lambda: NOW)
    captured: list = []

    class Workflow:
        async def run(self, request, channel, lease, send_notice):
            captured.append(request)

        async def shutdown(self):
            return None

    client.summary_workflow = Workflow()
    return client, captured, messages, path


def command(content: str, *, reference=None, fetched=None, fetch_error=None):
    channel = SimpleNamespace(id=2, type=discord.ChannelType.text, name="합성", send=AsyncMock())
    if fetch_error is not None:
        channel.fetch_message = AsyncMock(side_effect=fetch_error)
    else:
        channel.fetch_message = AsyncMock(return_value=fetched)
    guild = SimpleNamespace(id=1, me=object(), get_channel=lambda _id: channel)
    channel.guild = guild
    return SimpleNamespace(
        id=mid(100), guild=guild, channel=channel, content=content, webhook_id=None,
        author=SimpleNamespace(id=9, bot=False),
        type=discord.MessageType.reply if reference is not None else discord.MessageType.default,
        reference=reference,
    )


def ref(n: int, *, channel_id: int = 2, guild_id: int | None = 1):
    return SimpleNamespace(message_id=mid(n), channel_id=channel_id, guild_id=guild_id)


def send(client, event, monkeypatch):
    monkeypatch.setattr("yoyackbot.watch_gate.valid_channel", lambda *_: True, raising=False)

    async def scenario():
        try:
            await client.on_message(event)
        finally:
            await client.close()

    asyncio.run(scenario())
    return [call.args[0] for call in event.channel.send.await_args_list]


# T130-P3-A ------------------------------------------------------------------------------

@pytest.mark.parametrize(("content", "mode", "note"), [
    ("!!요약좀", SummaryMode.SHORT, None), ("!!요약좀 길게", SummaryMode.LONG, None),
    ("!!요약좀 자세히", SummaryMode.DETAILED, None), ("!!요약좀 시간순으로 해줘", SummaryMode.SHORT, "시간순으로 해줘"),
])
def test_reply_starts_at_the_cached_target(tmp_path, monkeypatch, content, mode, note) -> None:
    client, captured, _messages, _path = setup(tmp_path)
    event = command(content, reference=ref(3))
    assert send(client, event, monkeypatch) == []
    summary, = captured
    request = summary.requested_range
    assert request.kind is RequestKind.TIME and request.anchor_message_id == mid(3)
    assert request.start == NOW - timedelta(hours=4) + timedelta(minutes=3)
    assert request.trigger_message_id == mid(100)
    assert summary.scope == RangeScope(OptionKind.REPLY) and summary.mode is mode
    assert summary.request_note == note
    event.channel.fetch_message.assert_not_awaited()
    assert start_notice(summary.scope, mode).startswith("📝 답장한 메시지부터 채팅을 ")


def test_uncached_target_is_fetched_once(tmp_path, monkeypatch) -> None:
    client, captured, _messages, _path = setup(tmp_path)
    target = SimpleNamespace(id=mid(50), channel=SimpleNamespace(id=2), created_at=NOW - timedelta(hours=1))
    event = command("!!요약좀", reference=ref(50), fetched=target)
    assert send(client, event, monkeypatch) == []
    assert captured[0].requested_range.start == NOW - timedelta(hours=1)
    event.channel.fetch_message.assert_awaited_once_with(mid(50))


def test_plain_command_is_unchanged(tmp_path, monkeypatch) -> None:
    client, captured, _messages, _path = setup(tmp_path)
    assert send(client, command("!!요약좀 3시간"), monkeypatch) == []
    request = captured[0].requested_range
    assert request.anchor_message_id is None and request.start == NOW - timedelta(hours=3)
    assert captured[0].scope == RangeScope(OptionKind.HOURS, 3)


def test_notices_for_reply_ranges() -> None:
    scope = RangeScope(OptionKind.REPLY)
    assert start_notice(scope, SummaryMode.SHORT) == "📝 답장한 메시지부터 채팅을 요약해보겠소. ✍️"
    assert busy_notice(scope, SummaryMode.SHORT).startswith("⏳ 현재 답장한 메시지부터 채팅을 요약중이오. 🔄\n")
    ignored = RangeScope(OptionKind.REPLY, ignored_range=True)
    assert start_notice(ignored, SummaryMode.LONG) == (
        "📝 답장한 메시지부터 채팅을 길게 요약해보겠소. ✍️\n" + REPLY_IGNORED_LINE)
    with pytest.raises(ValueError):
        RangeScope(OptionKind.HOURS, 3, ignored_range=True)


def test_collector_includes_the_target_and_drops_same_time_earlier_messages(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({2}))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, verified_us=?, "
            "finished_us=?", (int(NOW.timestamp() * 1_000_000),) * 3)
    messages = SQLiteMessageStore(path, clock=lambda: NOW)
    same = NOW - timedelta(hours=1)
    for message_id, when in ((mid(1), same), (mid(2), same), (mid(3), same), (mid(4), NOW - timedelta(minutes=5)),
                             (mid(0), NOW - timedelta(hours=2))):
        messages.upsert(MessageRecord(message_id, 1, 2, 7, "가람", "합성", when), cached_at=NOW)
    collector = CacheOnlyCollector(watches, messages, SQLiteBackfillStore(path, clock=lambda: NOW),
                                   clock=lambda: NOW)
    channel = SimpleNamespace(type=discord.ChannelType.text, id=2, guild=SimpleNamespace(id=1))
    request = RangeRequest(RequestKind.TIME, NOW, start=same, anchor_message_id=mid(2))
    outcome = asyncio.run(collector.collect(channel, guild_id=1, channel_id=2, request=request))
    assert [row.message_id for row in outcome.messages] == [mid(2), mid(3), mid(4)]
    with pytest.raises(ValueError):
        RangeRequest(RequestKind.COUNT, NOW, count=3, anchor_message_id=mid(2))


# T130-P3-B ------------------------------------------------------------------------------

def test_range_written_with_a_reply_is_ignored_with_a_line(tmp_path, monkeypatch) -> None:
    client, captured, _messages, _path = setup(tmp_path)
    for written in ("!!요약좀 3시간", "!!요약좀 100개 길게"):
        captured.clear()
        event = command(written, reference=ref(3))
        assert send(client, event, monkeypatch) == []
        assert captured[0].scope == RangeScope(OptionKind.REPLY, ignored_range=True)
        assert captured[0].requested_range.anchor_message_id == mid(3)
        client, captured, _messages, _path = setup(tmp_path / written.split()[-1])


@pytest.mark.parametrize(("case", "expected"), [
    ("other_channel", OTHER_CHANNEL_NOTICE), ("other_guild", OTHER_CHANNEL_NOTICE),
    ("missing", MISSING_NOTICE), ("lookup", LOOKUP_FAILED_NOTICE),
    ("fetched_elsewhere", OTHER_CHANNEL_NOTICE), ("too_old", too_old_notice(30)),
])
def test_reply_refusals(tmp_path, monkeypatch, case, expected) -> None:
    client, captured, _messages, _path = setup(tmp_path)
    response = SimpleNamespace(status=404, reason="Not Found")
    event = {
        "other_channel": lambda: command("!!요약좀", reference=ref(3, channel_id=3)),
        "other_guild": lambda: command("!!요약좀", reference=ref(3, guild_id=5)),
        "missing": lambda: command("!!요약좀", reference=ref(60), fetch_error=discord.NotFound(response, "x")),
        "lookup": lambda: command("!!요약좀", reference=ref(60), fetch_error=OSError("x")),
        "fetched_elsewhere": lambda: command("!!요약좀", reference=ref(60), fetched=SimpleNamespace(
            channel=SimpleNamespace(id=3), created_at=NOW)),
        "too_old": lambda: command("!!요약좀", reference=ref(60), fetched=SimpleNamespace(
            channel=SimpleNamespace(id=2), created_at=NOW - timedelta(days=31))),
    }[case]()
    assert send(client, event, monkeypatch) == [expected]
    assert captured == []


def test_too_many_messages_after_the_target(tmp_path, monkeypatch) -> None:
    client, captured, _messages, _path = setup(tmp_path, YOYACK_MAX_MESSAGES="3")
    assert send(client, command("!!요약좀", reference=ref(1)), monkeypatch) == [too_many_notice(3)]
    client, captured, _messages, _path = setup(tmp_path / "ok", YOYACK_MAX_MESSAGES="3")
    assert send(client, command("!!요약좀", reference=ref(3)), monkeypatch) == []
    assert captured


def test_not_ready_comes_before_the_reply_lookup(tmp_path, monkeypatch) -> None:
    client, captured, _messages, path = setup(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE backfill_state SET phase='history'")
    event = command("!!요약좀", reference=ref(60))
    sent = send(client, event, monkeypatch)
    assert sent[0].startswith("⏳ 참을성을 기르시오") and captured == []
    event.channel.fetch_message.assert_not_awaited()
