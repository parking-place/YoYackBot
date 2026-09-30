"""The success cooldown defaults to one minute and caps older five-minute records (T102c-P1)."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.collection import CollectionOutcome
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore, cooldown_notice
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.state import AdmissionKind, ChannelStates

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)


def settings(**extra: str) -> Settings:
    return Settings.from_environment({"DISCORD_BOT_TOKEN": "x", **extra})


def test_default_is_sixty_seconds_and_environment_is_respected() -> None:
    assert settings().success_cooldown_seconds == 60
    assert settings(YOYACK_SUCCESS_COOLDOWN_SECONDS="300").success_cooldown_seconds == 300
    assert settings(YOYACK_SUCCESS_COOLDOWN_SECONDS="0").success_cooldown_seconds == 0
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    assert "YOYACK_SUCCESS_COOLDOWN_SECONDS=60" in example


def states_at(path: Path, clock: list[datetime], seconds: int = 60) -> ChannelStates:
    return ChannelStates(
        SQLiteCooldownStore(path, duration_seconds=seconds), clock=lambda: clock[0],
        monotonic=lambda: (clock[0] - NOW).total_seconds(),
    )


@pytest.mark.parametrize(
    ("elapsed", "kind", "remaining"),
    [(0, AdmissionKind.COOLDOWN, 60), (59, AdmissionKind.COOLDOWN, 1),
     (60, AdmissionKind.ACCEPTED, 0), (61, AdmissionKind.ACCEPTED, 0)],
)
def test_one_minute_boundary(tmp_path: Path, elapsed: int, kind: AdmissionKind,
                             remaining: int) -> None:
    async def scenario() -> None:
        clock = [NOW]
        states = states_at(tmp_path / "c.db", clock)
        await states.admit(1, 2)
        await states.finish_success(1, 2, NOW)
        clock[0] = NOW + timedelta(seconds=elapsed)
        admission = await states.admit(1, 2)
        assert admission.kind is kind and admission.remaining_seconds == remaining
        if kind is AdmissionKind.COOLDOWN:
            assert cooldown_notice(admission.remaining_seconds) == (
                f"아직은 때가 아니오. {remaining // 60:02d}분 {remaining % 60:02d}초 뒤에 오시오."
            )

    asyncio.run(scenario())


def test_five_minute_record_is_capped_at_sixty_seconds_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    SQLiteCooldownStore(path, duration_seconds=300).record_success(1, 2, NOW)
    with sqlite3.connect(path) as connection:
        before = connection.execute("SELECT * FROM summary_cooldowns").fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    async def scenario() -> None:
        for _restart in range(2):
            admission = await states_at(path, [NOW + timedelta(seconds=10)]).admit(1, 2)
            assert admission.kind is AdmissionKind.COOLDOWN
            assert admission.remaining_seconds == 60

    asyncio.run(scenario())
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM summary_cooldowns").fetchall() == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version == 5


@pytest.mark.parametrize("outcome", ["success", "empty", "failure"])
def test_only_full_success_starts_the_cooldown(
    outcome: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoyackbot.workflow import SummaryWorkflow

    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    class Collector:
        async def collect(self, _channel, *, request, **_kwargs):
            rows = () if outcome == "empty" else (
                MessageRecord(1, 1, 2, 3, "합성", "합성 대화", NOW - timedelta(minutes=1)),)
            return CollectionOutcome(rows, 0, request.accepted_at, 0, False)

    class Engine:
        async def summarize(self, *_args, **_kwargs):
            if outcome == "failure":
                raise RuntimeError("synthetic")
            return SummaryResult("합성 요약이오.", "synthetic", 1)

    class Publisher:
        async def publish(self, _request, _result, _messages):
            return PublicationReceipt((9,), NOW)

    async def scenario() -> None:
        clock = [NOW]
        states = states_at(tmp_path / "c.db", clock, seconds=settings().success_cooldown_seconds)
        workflow = SummaryWorkflow(Collector(), Engine(), Publisher(), states)  # type: ignore[arg-type]

        async def notice(_value: str) -> None:
            return None

        request = SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW,
                                                       start=NOW - timedelta(hours=1)))
        channel = SimpleNamespace(type=discord.ChannelType.text, id=2,
                                  guild=SimpleNamespace(id=1), name="합성")
        await workflow.run(request, channel, SimpleNamespace(valid=lambda: True), notice)  # type: ignore[arg-type]
        admission = await states.admit(1, 2)
        expected = AdmissionKind.COOLDOWN if outcome == "success" else AdmissionKind.ACCEPTED
        assert admission.kind is expected
        if outcome == "success":
            assert admission.remaining_seconds == 60

    asyncio.run(scenario())
