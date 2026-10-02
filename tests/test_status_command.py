"""`!!요약좀 상태` reports only this Guild, read-only, and never a false healthy state (T101-P5)."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import MessageRecord
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.parser import RouteKind, route_trigger
from yoyackbot.status_report import (
    StatusReport,
    collect_status,
    database_bytes,
    model_label,
    status_message,
)
from yoyackbot.watch_gate import UNWATCHED_NOTICE
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
READY_MODEL = "gpt-6-luna / low"


def settings(path: Path, **extra: str) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DB_PATH": str(path), **extra,
    })


def seeded(tmp_path: Path, *, success: bool = True) -> Path:
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10, 11}))
    watches.replace(2, frozenset({20, 21, 22}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    for message_id, guild_id, channel_id in (
        (1, 1, 10), (2, 1, 10), (3, 1, 11), (4, 2, 20), (5, 2, 20), (6, 2, 21), (7, 2, 22),
    ):
        store.upsert(MessageRecord(message_id, guild_id, channel_id, 9, "합성", "합성 대화",
                                   NOW - timedelta(hours=1)), cached_at=NOW)
    if success:
        cooldowns = SQLiteCooldownStore(path)
        cooldowns.record_success(1, 10, NOW - timedelta(hours=3))
        cooldowns.record_success(1, 11, NOW - timedelta(minutes=23))
        cooldowns.record_success(2, 20, NOW - timedelta(minutes=1))
    return path


def ready(_settings: Settings) -> str:
    return READY_MODEL


def report_for(path: Path, guild_id: int = 1, **kwargs: object) -> str:
    report = collect_status(settings(path), guild_id, gateway_ready=kwargs.pop("gateway", True),
                            model_reader=kwargs.pop("model", ready))
    return status_message(report, NOW)


def test_current_guild_values_only(tmp_path: Path) -> None:
    path = seeded(tmp_path)
    size = database_bytes(path)
    assert size is not None
    assert report_for(path) == "\n".join([
        "📜🔍 현재 형편을 살펴보았소. 🧐",
        "",
        "🩺 상태: 평온하오. 😌",
        "📡 주시 채널: 2곳이오.",
        "💬 캐시된 대화: 3건이오.",
        f"💾 DB 크기: {size / 1_000_000:.1f} MB이오.",
        "🤖 Codex: gpt-6-luna / low",
        "🕒 마지막 요약: 23분 전이오.",
    ])
    other = report_for(path, 2)
    assert "📡 주시 채널: 3곳이오." in other and "💬 캐시된 대화: 4건이오." in other
    assert "🕒 마지막 요약: 1분 전이오." in other


def test_unwatched_channel_success_is_not_the_last_summary(tmp_path: Path) -> None:
    path = seeded(tmp_path)
    SQLiteCooldownStore(path).record_success(1, 99, NOW - timedelta(seconds=5))
    assert "🕒 마지막 요약: 23분 전이오." in report_for(path)


def test_no_success_and_restart_use_persisted_records(tmp_path: Path) -> None:
    path = seeded(tmp_path, success=False)
    assert "🕒 마지막 요약: 기록이 없소." in report_for(path)
    assert "🩺 상태: 평온하오. 😌" in report_for(path)
    SQLiteCooldownStore(path).record_success(1, 10, NOW - timedelta(hours=2, minutes=5))
    assert "🕒 마지막 요약: 2시간 전이오." in report_for(path)


@pytest.mark.parametrize(
    ("age", "text"),
    [
        (timedelta(seconds=59), "방금 전이오."),
        (timedelta(seconds=60), "1분 전이오."),
        (timedelta(minutes=59, seconds=59), "59분 전이오."),
        (timedelta(hours=1), "1시간 전이오."),
        (timedelta(hours=23, minutes=59), "23시간 전이오."),
        (timedelta(days=1), "1일 전이오."),
        (timedelta(seconds=-30), "방금 전이오."),
    ],
)
def test_elapsed_boundaries(age: timedelta, text: str) -> None:
    report = StatusReport(True, 1, 1, 1, READY_MODEL, NOW - age, True)
    assert status_message(report, NOW).endswith("🕒 마지막 요약: " + text)


def test_large_counts_and_size_are_formatted_from_real_values() -> None:
    report = StatusReport(True, 4, 12_481, 18_400_000, READY_MODEL, None, True)
    text = status_message(report, NOW)
    assert "💬 캐시된 대화: 12,481건이오." in text and "💾 DB 크기: 18.4 MB이오." in text


def test_size_counts_wal_but_not_shm(tmp_path: Path) -> None:
    path = tmp_path / "messages.db"
    path.write_bytes(b"x" * 1000)
    assert database_bytes(path) == 1000
    (tmp_path / "messages.db-shm").write_bytes(b"x" * 500)
    (tmp_path / "messages.db-journal").write_bytes(b"x" * 300)
    assert database_bytes(path) == 1000
    (tmp_path / "messages.db-wal").write_bytes(b"x" * 250)
    assert database_bytes(path) == 1250
    assert database_bytes(tmp_path / "missing.db") is None


def unhealthy_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if "확인할 수 없소." in line]


def test_gateway_not_ready_is_never_calm(tmp_path: Path) -> None:
    text = report_for(seeded(tmp_path), gateway=False)
    assert "🩺 상태: 점검이 필요하오. 🚨" in text and "평온" not in text


def test_model_auth_failure_is_reported(tmp_path: Path) -> None:
    text = report_for(seeded(tmp_path), model=lambda _settings: None)
    assert "🩺 상태: 점검이 필요하오. 🚨" in text
    assert unhealthy_lines(text) == ["🤖 Codex: 확인할 수 없소."]


def test_missing_database_invents_no_numbers(tmp_path: Path) -> None:
    text = report_for(tmp_path / "missing.db")
    assert "🩺 상태: 점검이 필요하오. 🚨" in text
    assert len(unhealthy_lines(text)) == 4
    assert not (tmp_path / "missing.db").exists()


def test_locked_database_invents_no_numbers(tmp_path: Path) -> None:
    path = seeded(tmp_path)
    holder = sqlite3.connect(path)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        text = report_for(path)
    finally:
        holder.rollback()
        holder.close()
    assert "🩺 상태: 점검이 필요하오. 🚨" in text
    assert "📡 주시 채널: 확인할 수 없소." in text and "🕒 마지막 요약: 확인할 수 없소." in text


def test_status_read_does_not_write(tmp_path: Path) -> None:
    path = seeded(tmp_path)
    before = path.read_bytes()
    report_for(path)
    assert path.read_bytes() == before
    assert not (tmp_path / "messages.db-wal").exists()


def test_configured_model_other_than_the_contract_is_unknown(tmp_path: Path) -> None:
    other = settings(tmp_path / "db", YOYACK_CODEX_MODEL="gpt-6-sol")
    assert model_label(other) is None


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("!!요약좀 상태", RouteKind.STATUS),
        ("!!요약좀 상태 도움", RouteKind.HELP),
        ("!!요약좀 상태 부탁하오", RouteKind.SUMMARY),
        ("!!요약좀 1시간 상태", RouteKind.SUMMARY),
    ],
)
def test_status_is_one_exact_word(content: str, kind: RouteKind) -> None:
    assert route_trigger(content).kind is kind


@pytest.mark.parametrize("watched", [True, False])
def test_gateway_answers_status_only_in_watched_channels(tmp_path: Path, watched: bool) -> None:
    path = seeded(tmp_path)

    class NoWorkflow:
        async def run(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("status must not start a summary job")

        async def shutdown(self) -> None:
            return None

    async def scenario() -> None:
        store = MemoryWatchStore()
        store.replace(1, frozenset({10}) if watched else frozenset())
        client = YoYackClient(
            watch_store=store, settings=settings(path), clock=lambda: NOW,
            summary_workflow=NoWorkflow(),  # type: ignore[arg-type]
        )
        client.ready_event.set()
        channel = SimpleNamespace(type=discord.ChannelType.text, id=10, send=AsyncMock())
        event = SimpleNamespace(
            guild=SimpleNamespace(id=1), channel=channel, author=SimpleNamespace(bot=False, id=5),
            webhook_id=None, type=discord.MessageType.default, content="!!요약좀 상태",
        )
        try:
            await client.on_message(event)
        finally:
            await client.close()
        channel.send.assert_awaited_once()
        text = channel.send.await_args.args[0]
        assert channel.send.await_args.kwargs["allowed_mentions"].to_dict()["parse"] == []
        if watched:
            assert text.startswith("📜🔍 현재 형편을 살펴보았소. 🧐")
            assert "📡 주시 채널: 2곳이오." in text and "💬 캐시된 대화: 3건이오." in text
            assert str(path) not in text and "20" not in text.split("DB 크기")[0]
        else:
            assert text == UNWATCHED_NOTICE

    asyncio.run(scenario())
