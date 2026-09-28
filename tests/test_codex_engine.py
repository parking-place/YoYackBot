"""The summary engine sends only selected messages and recovers after a failed call."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yoyackbot.codex import CodexContract, CodexContractError, CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import InputWorkspace


def settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


def message(message_id: int, content: str) -> MessageRecord:
    return MessageRecord(message_id, 1, 10, 100, "시험 사용자", content,
                         datetime(2026, 9, 28, 12, 0, tzinfo=UTC))


def test_engine_excludes_trigger_and_returns_selected_count(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    class FakeRunner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            seen["rows"] = [json.loads(line) for line in workspace.log_file.read_bytes().splitlines()]
            seen["prompt"] = prompt
            seen["directory"] = workspace.directory
            workspace.close()
            return "시험 대화를 정리하였소."

    engine = CodexSummaryEngine(settings(tmp_path), FakeRunner())  # type: ignore[arg-type]
    result = asyncio.run(engine.summarize(
        [message(1, "합성 대화"), message(2, "!!요약좀")], trigger_message_id=2,
        channel_name="시험 채널", range_label="최근 1시간",
    ))
    assert result.text == "시험 대화를 정리하였소."
    assert result.model == "gpt-6-luna" and result.request_message_count == 1
    assert len(seen["rows"]) == 2
    assert seen["rows"][1]["body"] == "합성 대화"
    assert "합성 대화" not in seen["prompt"]
    assert not seen["directory"].exists()


def test_engine_failure_does_not_block_next_request(tmp_path: Path) -> None:
    paths: list[Path] = []

    class FlakyRunner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, _prompt: str) -> str:
            paths.append(workspace.directory)
            workspace.close()
            if len(paths) == 1:
                raise CodexRunError(CodexFailure.AUTH)
            return "다음 요청에 성공하였소."

    engine = CodexSummaryEngine(settings(tmp_path), FlakyRunner())  # type: ignore[arg-type]
    with pytest.raises(CodexRunError) as raised:
        asyncio.run(engine.summarize([message(1, "첫 요청")]))
    assert raised.value.kind is CodexFailure.AUTH
    result = asyncio.run(engine.summarize([message(2, "다음 요청")]))
    assert result.text == "다음 요청에 성공하였소."
    assert len(paths) == 2 and paths[0] != paths[1]
    assert all(not path.exists() for path in paths)


def test_engine_fails_closed_when_pinned_cli_or_auth_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = settings(tmp_path)
    monkeypatch.setattr(CodexContract, "version_matches", lambda _self: False)
    with pytest.raises(CodexContractError, match="version"):
        CodexSummaryEngine.from_settings(config)
    monkeypatch.setattr(CodexContract, "version_matches", lambda _self: True)
    monkeypatch.setattr(CodexContract, "authentication_ready", lambda _self, _path: False)
    with pytest.raises(CodexContractError, match="authenticated"):
        CodexSummaryEngine.from_settings(config)
