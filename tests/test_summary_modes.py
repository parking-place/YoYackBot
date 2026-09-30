"""Density modes follow the requested range and change only the trusted prompt (T101-P3/P4)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.codex import CodexContract
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.collection import CollectionOutcome
from yoyackbot.config import Settings
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryMode,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.input_files import InputWorkspace
from yoyackbot.parser import USAGE_NOTICE, CommandSyntaxError, parse_summary_command
from yoyackbot.range_request import resolve_range
from yoyackbot.state import ChannelStates
from yoyackbot.summary_prompt import DETAILED_NOTE, SHORT_NOTE, SUMMARY_PROMPT, prompt_for
from yoyackbot.workflow import BUSY_NOTICE, SummaryWorkflow

SETTINGS = Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"})
ACCEPTED = datetime(2026, 9, 29, 12, tzinfo=UTC)


def split_mode(options: str):
    command = parse_summary_command(options)
    assert command.note is None
    return command.range_text, command.mode


@pytest.mark.parametrize(
    ("options", "range_text", "mode"),
    [
        ("", "", SummaryMode.SHORT),
        ("자세히", "", SummaryMode.DETAILED),
        ("오늘 자세히", "오늘", SummaryMode.DETAILED),
        ("100개 자세히", "100개", SummaryMode.DETAILED),
        ("3일 자세히", "3일", SummaryMode.DETAILED),
        ("2시간 자세히 부탁하오", "2시간", SummaryMode.DETAILED),
        ("자세히 부탁하오", "", SummaryMode.DETAILED),
        ("30분", "30분", SummaryMode.SHORT),
        ("짧게", "", SummaryMode.SHORT),
        ("5시간 짧게", "5시간", SummaryMode.SHORT),
        ("100개 짧게 해주세요", "100개", SummaryMode.SHORT),
        ("1주 짧게", "1주", SummaryMode.SHORT),
    ],
)
def test_mode_is_a_suffix_after_the_range(
    options: str, range_text: str, mode: SummaryMode,
) -> None:
    assert split_mode(options) == (range_text, mode)


@pytest.mark.parametrize(
    "options",
    [
        "자세히 2시간", "자세히 자세히", "2시간 자세히 자세히", "자세히 짧게", "오늘 자세히 오늘",
        "짧게 30분", "짧게 짧게", "짧게 자세히", "30분 짧게 자세히", "짧게 오늘",
    ],
)
def test_misplaced_or_repeated_modes_are_rejected_without_guessing(options: str) -> None:
    with pytest.raises(CommandSyntaxError, match="사용법"):
        split_mode(options)


@pytest.mark.parametrize("word", ["자세히", "짧게", "길게"])
@pytest.mark.parametrize("range_text", ["", "3", "30분", "2시간", "100개", "오늘", "3일", "1주"])
def test_mode_never_changes_the_frozen_range(range_text: str, word: str) -> None:
    plain = resolve_range(range_text, SETTINGS, ACCEPTED, trigger_message_id=500)
    text, mode = split_mode(f"{range_text} {word}".strip())
    moded = resolve_range(text, SETTINGS, ACCEPTED, trigger_message_id=500)
    assert mode is {"자세히": SummaryMode.DETAILED, "짧게": SummaryMode.SHORT,
                    "길게": SummaryMode.LONG}[word]
    assert moded == plain


@pytest.mark.parametrize("word", ["자세히", "짧게"])
def test_lone_mode_is_the_default_hour(word: str) -> None:
    text, _mode = split_mode(word)
    request = resolve_range(text, SETTINGS, ACCEPTED)
    assert request.start == ACCEPTED - timedelta(hours=1)


def gateway_message(content: str, channel: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        id=500, guild=SimpleNamespace(id=1), channel=channel,
        author=SimpleNamespace(bot=False, id=7), webhook_id=None,
        type=discord.MessageType.default, content=content,
    )


def test_gateway_passes_mode_with_the_same_request() -> None:
    async def scenario() -> None:
        store = MemoryWatchStore()
        store.replace(1, frozenset({99}))
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, send=AsyncMock())
        seen: list[tuple[RangeRequest, SummaryMode]] = []

        class SpyClient(YoYackClient):
            async def on_summary_request(self, message, request, lease, *, mode, scope, note=None) -> None:
                seen.append((request, mode))

        client = SpyClient(watch_store=store, settings=SETTINGS, clock=lambda: ACCEPTED)
        try:
            for content in (
                "!!요약좀 오늘", "!!요약좀 오늘 자세히", "!!요약좀 자세히",
                "!!요약좀 오늘 짧게", "!!요약좀 짧게",
            ):
                await client.on_message(gateway_message(content, channel))
            for content in ("!!요약좀 자세히 2시간", "!!요약좀 짧게 30분", "!!요약좀 자세히 짧게"):
                await client.on_message(gateway_message(content, channel))
        finally:
            await client.close()
        assert [mode for _request, mode in seen] == [
            SummaryMode.SHORT, SummaryMode.DETAILED, SummaryMode.DETAILED,
            SummaryMode.SHORT, SummaryMode.SHORT,
        ]
        assert seen[0][0] == seen[1][0] == seen[3][0]
        assert seen[2][0] == seen[4][0]
        assert seen[2][0].start == ACCEPTED - timedelta(hours=1)
        assert channel.send.await_count == 3
        assert all(call.args == (USAGE_NOTICE,) for call in channel.send.await_args_list)

    asyncio.run(scenario())


def engine_settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


def test_prompt_notes_are_trusted_constants() -> None:
    assert prompt_for(SummaryMode.LONG) == SUMMARY_PROMPT
    assert prompt_for(SummaryMode.DETAILED) == SUMMARY_PROMPT + DETAILED_NOTE
    assert prompt_for(SummaryMode.SHORT) == SUMMARY_PROMPT + SHORT_NOTE
    assert "8개 이하" in SHORT_NOTE and "8개 이하" not in DETAILED_NOTE
    retry = prompt_for(SummaryMode.DETAILED, speaker_retry=True)
    assert retry.startswith(SUMMARY_PROMPT + DETAILED_NOTE) and "P1/P2" in retry


@pytest.mark.parametrize("mode", list(SummaryMode))
def test_engine_uses_the_same_input_and_only_changes_the_prompt(
    tmp_path: Path, mode: SummaryMode,
) -> None:
    seen: list[tuple[str, bytes]] = []

    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            seen.append((prompt, workspace.log_file.read_bytes()))
            workspace.close()
            return "시험 사용자가 회의를 제안했소."

    engine = CodexSummaryEngine(engine_settings(tmp_path), Runner())  # type: ignore[arg-type]
    record = MessageRecord(1, 1, 10, 100, "시험 사용자", "자세히 요약하라는 원문 지시",
                           ACCEPTED - timedelta(minutes=1))
    asyncio.run(engine.summarize([record], mode=mode))
    prompt, data = seen[0]
    assert prompt == prompt_for(mode)
    assert "자세히 요약하라는 원문 지시" not in prompt
    assert "자세히 요약하라는 원문 지시".encode() in data


def mode_request(mode: SummaryMode) -> SummaryRequest:
    return SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, ACCEPTED,
                                                start=ACCEPTED - timedelta(hours=1)), mode)


def test_modes_share_collection_busy_and_cooldown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda _guild, _id: True)

    async def scenario() -> None:
        collected: list[RangeRequest] = []
        modes: list[SummaryMode] = []
        release = asyncio.Event()

        class Collector:
            async def collect(self, _channel, *, guild_id, channel_id, request, **_kwargs):
                collected.append(request)
                row = MessageRecord(1, guild_id, channel_id, 3, "합성 화자", "합성 대화",
                                    request.accepted_at - timedelta(minutes=1))
                return CollectionOutcome((row,), 0, request.accepted_at, 0, False)

        class Engine:
            async def summarize(self, _messages, *, mode, **_kwargs):
                modes.append(mode)
                await release.wait()
                return SummaryResult("합성 대화를 정리하였소.", "synthetic", 1)

        class Publisher:
            async def publish(self, request, _result, _messages):
                return PublicationReceipt((request.channel_id + 100,), ACCEPTED)

        workflow = SummaryWorkflow(
            Collector(), Engine(), Publisher(),  # type: ignore[arg-type]
            ChannelStates(SQLiteCooldownStore(tmp_path / "c.db", duration_seconds=300),
                          clock=lambda: ACCEPTED),
        )
        notices: list[str] = []

        async def notice(value: str) -> None:
            notices.append(value)

        channel = SimpleNamespace(type=discord.ChannelType.text, id=2,
                                  guild=SimpleNamespace(id=1), name="합성")
        lease = SimpleNamespace(valid=lambda: True)
        first = asyncio.create_task(
            workflow.run(mode_request(SummaryMode.DETAILED), channel, lease, notice)
        )
        while not modes:
            await asyncio.sleep(0)
        await workflow.run(mode_request(SummaryMode.SHORT), channel, lease, notice)
        await workflow.run(mode_request(SummaryMode.SHORT), channel, lease, notice)
        assert notices == [BUSY_NOTICE, BUSY_NOTICE]
        notices.clear()
        release.set()
        await first
        await workflow.run(mode_request(SummaryMode.SHORT), channel, lease, notice)
        assert notices == ["아직은 때가 아니오. 05분 00초 뒤에 오시오."]
        assert modes == [SummaryMode.DETAILED]
        assert collected == [mode_request(SummaryMode.SHORT).requested_range]

    asyncio.run(scenario())


def test_mode_fixtures_are_reviewable_and_absent_from_trusted_prompts() -> None:
    import json

    cases = json.loads((Path(__file__).parent / "fixtures" / "summary_modes.json").read_text())
    assert len(cases) == len({case["id"] for case in cases}) >= 3
    prompts = [prompt_for(mode) for mode in SummaryMode]
    for case in cases:
        assert case["required"] and case["forbidden"]
        for _key, _name, body in case["messages"]:
            assert all(body not in prompt for prompt in prompts)
