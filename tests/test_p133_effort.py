"""1.3.3-P1: judge and idiom pick run at low, every call logs effort, tool runs and tokens
(T133-P1-A/B)."""

import asyncio
import importlib.util
import json
import logging
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from rating_fakes import candidates
from test_codex_runner import runner as sandbox_runner
from test_p130_idiom import FOUR, PICK
from test_p130_idiom import Runner as IdiomRunner
from test_p130_rating_judge import BODY, NOW, ROWS, TEN, Runner, settings

from yoyackbot import timing
from yoyackbot.codex import CodexContract, CodexFailure
from yoyackbot.codex_engine import LOW_EFFORT_CALLS, CodexSummaryEngine
from yoyackbot.codex_runner import _EFFORT, CodexRunError, _invoke, call_effort, fast_tier
from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import InputWorkspace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/show_timings.py"
SUMMARY_PATH = ["summary", "summary_retry", "candidates", "judge", "candidates_retry"]


def recording(base, effort):
    class Recording(base):
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", effort)

        def __init__(self, *args) -> None:
            super().__init__(*args)
            self.efforts: list[str | None] = []

        async def execute(self, workspace, prompt):
            self.efforts.append(_EFFORT.get())
            return await super().execute(workspace, prompt)

    return Recording


def five_call_summary(tmp_path, effort):
    leaked = "- **__P1__**: 라면을 꺼냈소."
    runner = recording(Runner, effort)(
        [leaked, BODY], [candidates(*TEN[:2]), candidates(TEN[8])], ["비슷함: 1, 2\n선택: 없음"],
    )
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]

    async def scenario():
        line = timing.begin()
        await engine.summarize(ROWS)
        return line

    return runner, asyncio.run(scenario())


# T133-P1-A ------------------------------------------------------------------------------

def test_only_the_judge_and_the_idiom_pick_are_lowered() -> None:
    assert LOW_EFFORT_CALLS == {"judge", "idiom_select"}


def test_summary_path_efforts_with_medium_configured(tmp_path) -> None:
    runner, line = five_call_summary(tmp_path, "medium")
    assert [c.label for c in line.calls] == SUMMARY_PATH
    assert runner.efforts == ["medium", "medium", "medium", "low", "medium"]
    assert [c.effort for c in line.calls] == runner.efforts


def test_a_low_setting_keeps_every_call_low(tmp_path) -> None:
    runner, _line = five_call_summary(tmp_path, "low")
    assert runner.efforts == ["low"] * 5


@pytest.mark.parametrize(("effort", "expected"), [("medium", ["medium", "medium", "low"]), ("low", ["low"] * 3)])
def test_idiom_path_efforts(tmp_path, effort, expected) -> None:
    runner = recording(IdiomRunner, effort)(["틀림", FOUR, PICK])
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]
    rows = [MessageRecord(n, 1, 2, 7, "가람", f"대화 {n}", NOW - timedelta(minutes=5 - n)) for n in range(1, 4)]
    asyncio.run(engine.idiom(rows))
    assert runner.efforts == expected


def test_the_sandbox_command_uses_the_call_effort_with_or_without_fast(tmp_path) -> None:
    isolated = sandbox_runner(tmp_path)
    isolated = replace(isolated, contract=replace(isolated.contract, reasoning_effort="medium"))

    async def one(effort, fast):
        with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
            async with call_effort(effort), fast_tier(fast):
                await asyncio.sleep(0)
                return isolated.command(workspace)

    async def scenario():
        return await asyncio.gather(one("low", True), one(None, False), one("medium", True),
                                    one("xhigh", False), one("high", False))

    low_fast, default, medium_fast, refused, high = asyncio.run(scenario())
    assert "model_reasoning_effort=low" in low_fast and 'service_tier="priority"' in low_fast
    assert "model_reasoning_effort=medium" in default and 'service_tier="priority"' not in default
    assert "model_reasoning_effort=medium" in medium_fast
    assert "model_reasoning_effort=medium" in refused  # an unknown effort never reaches the CLI
    assert "model_reasoning_effort=high" in high  # 1.4.0: the notice rewrite, per call only
    assert _EFFORT.get() is None


# T133-P1-B ------------------------------------------------------------------------------

def feed(chunks):
    async def scenario():
        line = timing.begin()
        async with timing.codex_call("summary", "medium"):
            watch = timing.OutputWatch()
            for chunk in chunks:
                watch.feed(chunk)
            watch.finish()
        return line.payload("summary", "r", "success")["codex"][0]

    return asyncio.run(scenario())


def test_tool_runs_and_tokens_are_counted_across_chunks() -> None:
    call = feed([b"OpenAI Codex v0.158.0\n--------\nuser\n\xe2\x80\x8bexec\nprompt\n", b"codex\nex",
                 b"ec\n/bin/bash -lc 'cat x'\nexec\n/bin/bash -lc 'sed -n 1,9p x'\ncodex\nanswer\ntokens us",
                 b"ed\n22,074\n"])
    assert (call["execs"], call["tokens"], call["effort"]) == (2, 22074, "medium")
    assert call["first_output"] is not None


@pytest.mark.parametrize("chunks", [
    [b"user\nprompt\ncodex\nanswer\ntokens used\n1,234"],          # last line without newline
    [b"user\nprompt\ncodex\nanswer\ntokens used\n", b"1234\n"],
])
def test_tokens_at_the_very_end(chunks) -> None:
    assert feed(chunks)["tokens"] in (1234,)


def test_odd_token_lines_are_ignored() -> None:
    call = feed([b"codex\ntokens used\nmany\ntokens used\n" + b"9" * 40 + b"\n"])
    assert call["tokens"] is None and call["execs"] == 0


def test_prompt_lines_that_look_like_markers_are_neutralized() -> None:
    prompt = "규칙\n exec \ncodex\n가운데 codex 단어\ntokens used\n12"
    sent = timing.neutralize_markers(prompt)
    assert sent.split("\n")[1] == "\u200b exec " and sent.split("\n")[2] == "\u200bcodex"
    assert "가운데 codex 단어" in sent and sent.endswith("\u200btokens used\n12")
    assert timing.neutralize_markers("평범한 프롬프트") == "평범한 프롬프트"
    call = feed([b"user\n" + sent.encode() + b"\ncodex\nanswer\n"])
    assert call["execs"] == 0


def test_failed_calls_drop_their_counts() -> None:
    async def scenario():
        line = timing.begin()
        with pytest.raises(CodexRunError):
            async with timing.codex_call("judge", "low"):
                watch = timing.OutputWatch()
                watch.feed(b"codex\nexec\nexec\ntokens used\n500\n")
                watch.finish()
                raise CodexRunError(CodexFailure.TIMEOUT)
        return line.payload("summary", "r", "model_error")["codex"][0]

    call = asyncio.run(scenario())
    assert (call["result"], call["execs"], call["tokens"], call["effort"]) == ("error", None, None, "low")


def test_a_real_process_reports_tool_runs_and_tokens(tmp_path) -> None:
    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\ncat >/dev/null\nprintf 'OpenAI Codex\\nuser\\nprompt\\ncodex\\nexec\\nls\\n' >&2\n"
                    "sleep 0.1\nprintf 'exec\\ncat\\ncodex\\nanswer\\ntokens used\\n3,210\\n' >&2\necho done\n")
    fake.chmod(0o755)

    async def scenario():
        line = timing.begin()
        async with timing.codex_call("summary", "medium"):
            await _invoke([str(fake)], b"prompt", {"PATH": "/usr/bin:/bin"}, 10, 1000)
        return line.calls[0]

    call = asyncio.run(scenario())
    assert (call.execs, call.tokens) == (2, 3210)


def test_payload_allowlists_the_effort() -> None:
    line = timing.Timeline()
    line.calls.append(timing.CodexCall("judge", 1, line, 2, 3, "ok", effort="xhigh", execs=1, tokens=9))
    assert line.payload("summary", "r", "success")["codex"][0]["effort"] is None


def test_the_table_shows_the_new_fields_and_still_reads_old_lines(capsys, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("show_timings", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    base = {"event": "request_timing", "kind": "summary", "outcome": "success", "discord_delay_ms": 5,
            "steps": [["received", 0], ["posted", 9000]], "total_ms": 9001}
    new = {**base, "request_id": "new", "codex": [{"n": 1, "call": "judge", "start": 10, "first_output": 3000,
                                                    "end": 8000, "result": "ok", "effort": "low", "execs": 0,
                                                    "tokens": 31000}]}
    old = {**base, "request_id": "old", "codex": [{"n": 1, "call": "summary", "start": 10, "first_output": 3000,
                                                    "end": 8000, "result": "ok"}]}
    monkeypatch.setattr("sys.stdin", [json.dumps(old), json.dumps(new)])
    monkeypatch.setattr("sys.argv", ["show_timings.py"])
    module.main()
    out = capsys.readouterr().out
    assert "[호출 7,990 · low · 도구 0회 · 31,000토큰]" in out and "[호출 7,990]" in out


def test_timing_lines_keep_no_text(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    _runner, line = five_call_summary(tmp_path, "medium")
    line.emit("summary", "r", "success")
    text = caplog.records[-1].message
    assert '"effort":"low"' in text and "라면" not in text and "가람" not in text
