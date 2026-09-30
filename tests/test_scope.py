"""Display labels and the ready/not-ready boundary for 1.0.2 notices (T102-P1)."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.backfill import NOT_READY_NOTICE, SQLiteBackfillStore, summary_ready
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import SummaryMode
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.parser import CommandLimitError, OptionKind, parse_summary_command
from yoyackbot.scope import RangeScope, busy_notice, describe_range, start_notice
from yoyackbot.watch_store import SQLiteWatchStore

SETTINGS = Settings.from_environment({"DISCORD_BOT_TOKEN": "synthetic"})
BUSY_TAIL = "\n참을성을 가져보시오."


def split_mode(options: str):
    command = parse_summary_command(options)
    assert command.note is None
    return command.range_text, command.mode


@pytest.mark.parametrize(
    ("options", "start", "busy"),
    [
        ("", "1시간 채팅을 요약해보겠소.", "현재 1시간 분 채팅을 요약중이오."),
        ("3", "3시간 채팅을 요약해보겠소.", "현재 3시간 분 채팅을 요약중이오."),
        ("30분", "30분 채팅을 요약해보겠소.", "현재 30분간의 채팅을 요약중이오."),
        ("2시간", "2시간 채팅을 요약해보겠소.", "현재 2시간 분 채팅을 요약중이오."),
        ("10일", "10일 채팅을 요약해보겠소.", "현재 10일 분 채팅을 요약중이오."),
        ("30일", "30일 채팅을 요약해보겠소.", "현재 30일 분 채팅을 요약중이오."),
        ("1주", "1주 채팅을 요약해보겠소.", "현재 1주 분 채팅을 요약중이오."),
        ("오늘", "오늘 채팅을 요약해보겠소.", "현재 오늘 채팅을 요약중이오."),
        ("100개", "최근 100개 채팅을 요약해보겠소.", "현재 최근 100개 채팅을 요약중이오."),
        ("자세히", "1시간 채팅을 자세히 요약해보겠소.", "현재 1시간 분 채팅을 자세히 요약중이오."),
        ("5시간 짧게", "5시간 채팅을 요약해보겠소.", "현재 5시간 분 채팅을 요약중이오."),
        ("5시간 길게", "5시간 채팅을 길게 요약해보겠소.", "현재 5시간 분 채팅을 길게 요약중이오."),
        ("100개 자세히 부탁하오", "최근 100개 채팅을 자세히 요약해보겠소.",
         "현재 최근 100개 채팅을 자세히 요약중이오."),
        ("30분 길게", "30분 채팅을 길게 요약해보겠소.", "현재 30분간의 채팅을 길게 요약중이오."),
    ],
)
def test_contract_table_wording(options: str, start: str, busy: str) -> None:
    range_text, mode = split_mode(options)
    scope = describe_range(range_text, SETTINGS)
    assert start_notice(scope, mode) == start
    assert busy_notice(scope, mode) == busy + BUSY_TAIL


@pytest.mark.parametrize(("minutes", "text"), [("60", "1시간"), ("120", "2시간"), ("90", "90분")])
def test_default_range_follows_configured_minutes(minutes: str, text: str) -> None:
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DEFAULT_MINUTES": minutes,
    })
    assert describe_range("", settings).text == text


def test_day_limit_is_the_released_thirty_days() -> None:
    assert SETTINGS.max_days == 30 and SETTINGS.default_minutes == 60
    assert describe_range("30일", SETTINGS) == RangeScope(OptionKind.DAYS, 30)
    with pytest.raises(CommandLimitError):
        describe_range("31일", SETTINGS)
    lowered = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_MAX_DAYS": "7"})
    with pytest.raises(CommandLimitError):
        describe_range("10일", lowered)


def test_labels_hold_only_validated_values() -> None:
    with pytest.raises(ValueError):
        RangeScope(OptionKind.DAYS, None)
    with pytest.raises(ValueError):
        RangeScope(OptionKind.TODAY, 3)
    with pytest.raises(ValueError):
        RangeScope(OptionKind.HOURS, 0)
    assert "<@" not in start_notice(describe_range("2시간", SETTINGS), SummaryMode.SHORT)


def backfill_db(tmp_path: Path) -> tuple[Path, SQLiteBackfillStore]:
    path = tmp_path / "messages.db"
    SQLiteWatchStore(path).replace(1, frozenset({99}))
    return path, SQLiteBackfillStore(path)


def set_state(path: Path, *, phase: str, first_watch: int, ready_notice: int | None) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase=?, first_watch=?, ready_notice_id=? "
            "WHERE guild_id=1 AND channel_id=99", (phase, first_watch, ready_notice),
        )


STATES = [
    ("history", 1, None, False),   # first 30-day collection
    ("overlap", 1, None, False),   # first collection overlap recheck
    ("ready", 1, None, False),     # collected, ready notice not posted yet
    ("overlap", 0, None, False),   # restart / disconnect gap recheck
    ("ready", 1, 555, True),
    ("ready", 0, None, True),      # migrated channel without first-watch notices
]


@pytest.mark.parametrize(("phase", "first_watch", "notice", "ready"), STATES)
def test_ready_boundary(tmp_path: Path, phase: str, first_watch: int,
                        notice: int | None, ready: bool) -> None:
    path, store = backfill_db(tmp_path)
    set_state(path, phase=phase, first_watch=first_watch, ready_notice=notice)
    assert summary_ready(store.get(1, 99)) is ready
    assert summary_ready(None) is False
    state = store.get(1, 99)
    assert state is not None and summary_ready(replace(state, phase="history")) is False


@pytest.mark.parametrize(("phase", "first_watch", "notice", "ready"), STATES)
def test_gateway_sends_not_ready_or_admits(
    tmp_path: Path, phase: str, first_watch: int, notice: int | None, ready: bool,
) -> None:
    path, _store = backfill_db(tmp_path)
    set_state(path, phase=phase, first_watch=first_watch, ready_notice=notice)
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path),
    })
    admitted: list[object] = []

    class SpyClient(YoYackClient):
        async def on_summary_request(self, message, request, lease, **kwargs) -> None:
            admitted.append(kwargs)

    async def scenario() -> None:
        client = SpyClient(
            watch_store=SQLiteWatchStore(path), message_store=SQLiteMessageStore(path),
            settings=settings, clock=lambda: datetime(2026, 9, 29, 12, tzinfo=UTC),
        )
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=AsyncMock())
        event = SimpleNamespace(
            id=500, guild=SimpleNamespace(id=1), channel=channel,
            author=SimpleNamespace(bot=False, id=7), webhook_id=None,
            type=discord.MessageType.default, content="!!요약좀 10일",
        )
        try:
            await client.on_message(event)
        finally:
            await client.close()
        if ready:
            assert len(admitted) == 1 and channel.send.await_count == 0
        else:
            assert admitted == []
            assert channel.send.await_args.args == (NOT_READY_NOTICE,)

    asyncio.run(scenario())
