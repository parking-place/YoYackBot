"""B10–B13: one output contract for every model answer, one pinned CLI path (T120-P4-A..D)."""

import asyncio
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.__main__ import main
from yoyackbot.codex import (
    PINNED_CLI_VERSION,
    CodexContract,
    CodexContractError,
    CodexFailure,
    pin_executable,
)
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError, SandboxedCodex
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryRequest
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.input_files import InputWorkspace
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.output_quality import OutputIssue, inspect_output
from yoyackbot.readiness import ReadinessError, ReadinessKind, check_ready
from yoyackbot.state import ChannelStatus
from yoyackbot.summary_prompt import REFUSAL_NOTICE
from yoyackbot.usage import UsageUnavailable, read_account_usage
from yoyackbot.watch_gate import WatchGate
from yoyackbot.watch_store import SQLiteWatchStore
from yoyackbot.workflow import build_workflow

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
BODY = "### 🚀 배포 일정\n- **__가람__**: 목요일로 정정했소. 📅"
RATING = "**요약창섭의 떡밥 한줄 평가** : 요일 퀴즈 풀다 날 샜단 말이오. 🗓️"
GOOD = f"{BODY}\n\n{RATING}"
ROWS = [MessageRecord(1, 1, 2, 100, "가람", "금요일 배포 어때요?", NOW - timedelta(hours=1))]


def settings(tmp_path: Path, **extra: str) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_DB_PATH": str(tmp_path / "cache.db"),
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
        **extra,
    })


class Runner:
    contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

    def __init__(self, answers: list[object]) -> None:
        self.answers = answers
        self.prompts: list[str] = []

    async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
        self.prompts.append(prompt)
        workspace.close()
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer  # type: ignore[return-value]


def summarize(tmp_path: Path, answers: list[object], note: str | None = None):
    runner = Runner(answers)
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]
    return asyncio.run(engine.summarize(ROWS, request_note=note)), runner


def fails(tmp_path: Path, answers: list[object], note: str | None = None) -> Runner:
    runner = Runner(answers)
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]
    with pytest.raises(CodexRunError) as error:
        asyncio.run(engine.summarize(ROWS, request_note=note))
    assert error.value.kind is CodexFailure.OUTPUT_INVALID
    return runner


# T120-P4-A ---------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "- **P1**: 금요일 배포를 제안했소.", "- __P1__: 금요일 배포를 제안했소.",
    "- **__P1__**: 금요일 배포를 제안했소.", "- __**P1**__: 금요일 배포를 제안했소.",
    "- 🙋 **__P1__**: 금요일 배포를 제안했소.", "**P2**는 반대했소.", "1. *P3*: 미뤘소.",
    "P1이 먼저 말을 꺼냈소.", "### P1: 배포",
])
def test_internal_keys_in_speaker_position_are_caught(line: str) -> None:
    assert inspect_output(f"### 🚀 배포\n{line}", ["금요일 배포 어때요?"]) is OutputIssue.SPEAKER_KEY


@pytest.mark.parametrize("text", [
    '> "P1: 지금 배포하자" 라고 했소.', "```\nP1: 로그 그대로\n```\n코드를 붙였소.",
    "- `P1`: 우선순위 표기를 두고 다퉜소.", "- **__가람__**: P2P 전송을 제안했소.",
    "- **__가람__**: 금요일 배포를 제안했소.",
])
def test_quotes_code_and_real_names_are_not_over_blocked(text: str) -> None:
    assert inspect_output(text, ["금요일 배포 어때요?"]) is None


@pytest.mark.parametrize("key", ["**__P1__**", "__**P1**__"])
def test_engine_retries_nested_key_once_and_never_publishes_it(tmp_path, key) -> None:
    leaked = f"### 🚀 배포\n- {key}: 금요일 배포를 제안했소.\n\n{RATING}"
    result, runner = summarize(tmp_path, [leaked, GOOD])
    assert result.text == GOOD and len(runner.prompts) == 2
    runner = fails(tmp_path, [leaked, leaked])
    assert len(runner.prompts) == 2


# T120-P4-B ---------------------------------------------------------------------------

@pytest.mark.parametrize(("answer", "note"), [
    (RATING, None), (RATING, "평가 빼줘"), (REFUSAL_NOTICE, None),
    (f"**{REFUSAL_NOTICE}**\n\n{RATING}", None), (f"---\n🚀✨\n\n{RATING}", None),
])
def test_answers_without_a_summary_body_are_retried_once_then_rejected(tmp_path, answer, note):
    runner = fails(tmp_path, [answer, answer], note)
    assert len(runner.prompts) == 2
    result, runner = summarize(tmp_path, [answer, GOOD], note)
    assert BODY in result.text and len(runner.prompts) == 2


@pytest.mark.parametrize("answer", ["   \n  ", "---\n🚀✨", "YOYACK_INPUT_UNAVAILABLE"])
def test_blank_or_unreadable_answer_is_rejected_without_retry(tmp_path, answer) -> None:
    assert len(fails(tmp_path, [answer]).prompts) == 1


def runtime(tmp_path: Path, monkeypatch, runner: Runner):
    config = settings(tmp_path)
    watches = SQLiteWatchStore(config.database_path)
    watches.replace(1, frozenset({2}))
    messages = SQLiteMessageStore(config.database_path, clock=lambda: NOW)
    with sqlite3.connect(config.database_path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, "
            "verified_us=?, finished_us=?", (int(NOW.timestamp() * 1_000_000),) * 3,
        )
    messages.upsert(ROWS[0], cached_at=NOW)
    channel = SimpleNamespace(type=discord.ChannelType.text, id=2, guild=SimpleNamespace(id=1),
                              name="합성 채널")
    channel.send = AsyncMock(return_value=SimpleNamespace(id=500, channel=channel, created_at=NOW))
    client = SimpleNamespace(get_channel=lambda _id: channel, clock=lambda: NOW,
                             cache_available=lambda: True)
    engine = CodexSummaryEngine(config, runner)  # type: ignore[arg-type]
    monkeypatch.setattr("yoyackbot.workflow.CodexSummaryEngine.from_settings", lambda _: engine)
    monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda *_: True)
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda *_: True)
    workflow = build_workflow(config, client, watches, messages)
    _, lease = WatchGate(watches).lease(1, 2)
    return workflow, channel, lease


@pytest.mark.parametrize(("answers", "note", "published"), [
    ([RATING, RATING], None, False),
    ([RATING, RATING], "평가 빼줘", False),
    ([REFUSAL_NOTICE, REFUSAL_NOTICE], None, False),
    (["  ", "unused"], None, False),
    ([GOOD], None, True),
])
def test_workflow_publishes_and_cools_down_only_with_a_body(tmp_path, monkeypatch, answers, note,
                                                             published) -> None:
    async def scenario() -> None:
        workflow, channel, lease = runtime(tmp_path, monkeypatch, Runner(list(answers)))
        notices = AsyncMock()
        request = SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW,
                                                         start=NOW - timedelta(days=1)),
                                 request_note=note)
        await workflow.run(request, channel, lease, notices)
        status = await workflow.states.status(1, 2)
        if published:
            assert channel.send.await_count >= 1 and status is ChannelStatus.COOLDOWN
            assert BODY in channel.send.await_args_list[0].args[0]
        else:
            channel.send.assert_not_awaited()
            assert status is ChannelStatus.IDLE
            assert notices.await_args_list[-1].args == (message_for(FailureKind.MODEL),)

    asyncio.run(scenario())


# T120-P4-C ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "**요약창섭의 떡밥 한줄 평가** : YOYACK_INPUT_UNAVAILABLE 요란하오.",
    "**요약창섭의 떡밥 한줄 평가** : /work/conversation.jsonl 을 다 읽었소.",
    "**요약창섭의 떡밥 한줄 평가** : P1의 떡밥이 제일 요란하오.",
    "**요약창섭의 떡밥 한줄 평가** : 병신같은 떡밥이오.",
    "평가: 요란하오.",
    "Too loud.",
    CodexRunError(CodexFailure.TIMEOUT),
])
def test_bad_regenerated_rating_is_left_out_and_the_body_kept(tmp_path, bad) -> None:
    result, runner = summarize(tmp_path, [BODY, bad])
    assert result.text == BODY and result.rating == "missing" and len(runner.prompts) == 2


@pytest.mark.parametrize("marker", ["YOYACK_INPUT_UNAVAILABLE", "/auth/auth.json"])
def test_first_answer_with_a_bad_rating_keeps_the_body_and_asks_again(tmp_path, marker) -> None:
    first = f"{BODY}\n\n**요약창섭의 떡밥 한줄 평가** : {marker} 요란하오."
    result, runner = summarize(tmp_path, [first, RATING])
    assert result.text == GOOD and result.rating == "retried" and len(runner.prompts) == 2


def test_first_answer_rating_with_an_internal_key_is_regenerated(tmp_path) -> None:
    first = f"{BODY}\n\n**요약창섭의 떡밥 한줄 평가** : P2의 떡밥이 요란하오."
    result, runner = summarize(tmp_path, [first, RATING])
    assert result.text == GOOD and len(runner.prompts) == 2


@pytest.mark.parametrize("bad_body", [
    "### 🚀 배포\n- **__가람__**: /work/conversation.jsonl 에서 읽었소.",
    "### 🚀 배포\n- **__가람__**: YOYACK_INPUT_UNAVAILABLE",
])
def test_bad_body_is_never_published_because_the_rating_is_fine(tmp_path, bad_body) -> None:
    assert len(fails(tmp_path, [f"{bad_body}\n\n{RATING}"]).prompts) == 1


def test_skip_request_and_three_call_cap(tmp_path) -> None:
    result, runner = summarize(tmp_path, [GOOD], "평가 빼줘")
    assert result.text == BODY and result.rating == "skipped" and len(runner.prompts) == 1
    leaked = "- **__P1__**: 금요일 배포를 제안했소."
    bad_rating = "**요약창섭의 떡밥 한줄 평가** : P1의 떡밥이오."
    result, runner = summarize(tmp_path, [leaked, f"{BODY}\n\n{bad_rating}", bad_rating])
    assert result.text == BODY and result.rating == "missing" and len(runner.prompts) == 3


# T120-P4-D ---------------------------------------------------------------------------

def cli(directory: Path, name: str, *, version: str = PINNED_CLI_VERSION, mode: int = 0o700) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(f"#!/bin/sh\necho '{version}'\n")
    path.chmod(mode)
    return path


def private_auth(tmp_path: Path) -> Path:
    directory = tmp_path / "model-auth"
    directory.mkdir(mode=0o700)
    (directory / "auth.json").write_text("{}")
    (directory / "auth.json").chmod(0o600)
    return directory


def ready_reason(config: Settings) -> str | None:
    try:
        check_ready(config)
    except ReadinessError as error:
        assert error.kind is ReadinessKind.MODEL
        return error.reason
    return None


def test_path_name_is_pinned_once_and_shared_by_every_consumer(tmp_path, monkeypatch) -> None:
    private_auth(tmp_path)
    binary = cli(tmp_path / "bin", "codex")
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}/usr/bin{os.pathsep}/bin")
    config = pin_executable(settings(tmp_path, YOYACK_CODEX_EXECUTABLE="codex"))
    assert config.codex_executable == str(binary)
    # A later PATH change cannot swap the file under the running service.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert ready_reason(config) is None
    contract = CodexContract.from_settings(config)
    assert contract.executable == str(binary)
    workspace = InputWorkspace.create((tmp_path / "inputs").absolute(), b"{}\n")
    runner = SandboxedCodex(contract, tmp_path / "model-auth" / "auth.json")
    command = runner.command(workspace)
    assert command[command.index("/bin/codex") - 1] == str(binary)
    workspace.close()
    seen = []

    async def fake_read_usage(command, **_kwargs):
        seen.append(command[0])
        raise UsageUnavailable("synthetic")

    monkeypatch.setattr("yoyackbot.usage.read_usage", fake_read_usage)
    with pytest.raises(UsageUnavailable):
        asyncio.run(read_account_usage(config.codex_executable, tmp_path / "model-auth" / "auth.json",
                                       (tmp_path / "inputs").absolute()))
    assert seen == [str(binary)]


@pytest.mark.parametrize(("case", "reason"), [
    ("absolute", None), ("missing_name", "executable_missing"),
    ("missing_file", "executable_missing"), ("not_runnable", "executable_not_runnable"),
    ("directory", "executable_not_runnable"), ("wrong_version", "version_mismatch"),
    ("relative", "config"), ("no_auth", "auth_file"),
])
def test_readiness_engine_and_usage_agree_before_any_run(tmp_path, monkeypatch, case, reason) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    if case != "no_auth":
        private_auth(tmp_path)
    executable = {
        "absolute": lambda: str(cli(tmp_path / "bin", "codex")),
        "missing_name": lambda: "codex-not-installed",
        "missing_file": lambda: str(tmp_path / "bin" / "absent"),
        "not_runnable": lambda: str(cli(tmp_path / "bin", "codex", mode=0o600)),
        "directory": lambda: str((tmp_path / "bin").mkdir() or tmp_path / "bin"),
        "wrong_version": lambda: str(cli(tmp_path / "bin", "codex", version="codex-cli 0.0.1")),
        "relative": lambda: "bin/codex",
        "no_auth": lambda: str(cli(tmp_path / "bin", "codex")),
    }[case]()
    config = pin_executable(settings(tmp_path, YOYACK_CODEX_EXECUTABLE=executable))
    assert ready_reason(config) == reason
    if reason is None:
        assert CodexSummaryEngine.from_settings(config).runner.contract.executable == executable
        return
    with pytest.raises(CodexContractError):
        CodexSummaryEngine.from_settings(config)
    if not os.path.isabs(config.codex_executable):
        with pytest.raises(UsageUnavailable):
            asyncio.run(read_account_usage(config.codex_executable,
                                           tmp_path / "model-auth" / "auth.json", tmp_path))


def test_check_ready_names_the_reason_without_the_path(tmp_path, monkeypatch, capsys) -> None:
    private_auth(tmp_path)
    secret_dir = tmp_path / "private-tools-dir"
    binary = cli(secret_dir, "codex", mode=0o600)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic")
    monkeypatch.setenv("YOYACK_DB_PATH", str(tmp_path / "cache.db"))
    monkeypatch.setenv("YOYACK_INPUT_DIRECTORY", str(tmp_path / "inputs"))
    monkeypatch.setenv("YOYACK_CODEX_AUTH_DIRECTORY", str(tmp_path / "model-auth"))
    monkeypatch.setenv("YOYACK_CODEX_EXECUTABLE", str(binary))
    monkeypatch.setattr(sys, "argv", ["yoyackbot", "check-ready"])
    assert main() == 2
    out = capsys.readouterr().out
    assert out.strip() == (
        "Readiness failed: model runtime or authentication unavailable (executable_not_runnable)"
    )
    assert str(secret_dir) not in out and json.dumps(str(secret_dir)) not in out
