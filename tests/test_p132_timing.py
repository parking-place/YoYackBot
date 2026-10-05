"""1.3.2-P1: one `request_timing` line per request with stage and Codex call ms (T132-P1-A/B)."""

import asyncio
import importlib.util
import json
import logging
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from rating_fakes import candidates
from test_p130_idiom import FOUR, PICK
from test_p130_idiom import Runner as IdiomRunner
from test_p130_idiom import context as idiom_context
from test_p130_idiom import event as idiom_event
from test_p130_rating_judge import BODY, NOW, OWN, ROWS, TEN, Runner, settings, workflow_context

from yoyackbot import timing
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError, _invoke
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryRequest
from yoyackbot.scope import describe_range

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/show_timings.py"


class Talking(Runner):
    """The 1.3.0 judge runner; each call reports a first output line like the CLI does."""

    async def execute(self, workspace, prompt):
        await asyncio.sleep(0.002)
        timing.first_output()
        await asyncio.sleep(0.002)
        return await super().execute(workspace, prompt)


class TalkingIdiom(IdiomRunner):
    async def execute(self, workspace, prompt):
        timing.first_output()
        return await super().execute(workspace, prompt)


def records(caplog, kind=None):
    found = [json.loads(r.message) for r in caplog.records if '"request_timing"' in r.message]
    return [item for item in found if kind is None or item["kind"] == kind]


def ordered(call: dict) -> bool:
    return call["start"] <= call["first_output"] <= call["end"]


# T132-P1-A ------------------------------------------------------------------------------

def test_five_summary_calls_are_named_in_order(tmp_path) -> None:
    leaked = "- **__P1__**: 라면을 꺼냈소."
    runner = Talking([leaked, BODY], [candidates(*TEN[:2]), candidates(TEN[8])], ["비슷함: 1, 2\n선택: 없음"])
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]

    async def scenario():
        line = timing.begin()
        await engine.summarize(ROWS)
        return line.payload("summary", "r", "success")

    payload = asyncio.run(scenario())
    calls = payload["codex"]
    # 1.3.3: the candidates start with the summary (P4); the rest stays in order.
    assert [c["call"] for c in calls] == ["summary", "candidates", "summary_retry", "judge", "candidates_retry"]
    assert [c["n"] for c in calls] == [1, 2, 3, 4, 5]
    assert all(ordered(c) and c["result"] == "ok" for c in calls)
    summary, cands, retry, judge, again = calls
    assert cands["start"] < summary["end"]
    assert all(a["end"] <= b["start"] for a, b in pairwise([summary, retry, judge, again]))
    assert judge["start"] >= max(retry["end"], cands["end"])


def test_idiom_calls_with_a_regeneration(tmp_path) -> None:
    engine = CodexSummaryEngine(settings(tmp_path), TalkingIdiom(["틀림", FOUR, PICK]))  # type: ignore[arg-type]
    rows = [MessageRecord(n, 1, 2, 7, "가람", f"대화 {n}", NOW - timedelta(minutes=5 - n)) for n in range(1, 4)]

    async def scenario():
        line = timing.begin()
        await engine.idiom(rows)
        return line.payload("idiom", "r", "success")

    calls = asyncio.run(scenario())["codex"]
    assert [c["call"] for c in calls] == ["idiom_candidates", "idiom_candidates_retry", "idiom_select"]
    assert all(ordered(c) for c in calls)


@pytest.mark.parametrize(("chunks", "found"), [
    ([b"OpenAI Codex v0.158.0\n--------\nuser\n", b"\xec\x9a\x94\xec\x95\xbd\n"], False),
    ([b"--------\nuser\nprompt\n", b"codex\n", b"answer\n"], True),
    ([b"user\nprompt\nco", b"dex\nanswer"], True),            # split across chunks
    ([b"warning: x\nthinking\n"], True),
    ([b"user\n  exec  \n"], True),
    ([b"a codex line\nnot codex at all\n"], False),
    ([b"x" * 100 + b"codex", b"\n"], False),                  # tail of a long line
    ([b"codex"], False),                                      # no line end yet
])
def test_first_output_line_detection(chunks, found) -> None:
    async def scenario():
        line = timing.begin()
        async with timing.codex_call("summary"):
            watch = timing.OutputWatch()
            for chunk in chunks:
                watch.feed(chunk)
        return line.calls[0].first_output_ms is not None

    assert asyncio.run(scenario()) is found


def test_a_real_process_reports_start_first_output_and_end(tmp_path) -> None:
    fake = tmp_path / "fake-codex"
    fake.write_text("#!/bin/sh\ncat >/dev/null\necho 'OpenAI Codex v0.158.0' >&2\nsleep 0.3\n"
                    "printf 'codex\\n' >&2\nsleep 0.3\necho done\n")
    fake.chmod(0o755)

    async def scenario():
        line = timing.begin()
        async with timing.codex_call("summary"):
            code, out, _err = await _invoke([str(fake)], b"prompt", {"PATH": "/usr/bin:/bin"}, 10, 1000)
        return code, out, line.calls[0]

    code, out, call = asyncio.run(scenario())
    assert (code, out) == (0, b"done\n")
    assert call.first_output_ms - call.start_ms >= 250 and call.end_ms - call.first_output_ms >= 250


def test_failed_and_cancelled_calls(tmp_path) -> None:
    async def scenario():
        line = timing.begin()
        with pytest.raises(CodexRunError):
            async with timing.codex_call("judge"):
                raise CodexRunError(CodexFailure.TIMEOUT)

        async def slow():
            async with timing.codex_call("summary"):
                await asyncio.sleep(10)

        task = asyncio.create_task(slow())
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return line.payload("summary", "r", "cancelled")["codex"]

    calls = asyncio.run(scenario())
    assert [(c["call"], c["result"], c["first_output"]) for c in calls] == [
        ("judge", "error", None), ("summary", "cancelled", None)]


def test_concurrent_requests_keep_their_own_lines(tmp_path) -> None:
    async def one(label, pause):
        line = timing.begin()
        async with timing.codex_call(label):
            await asyncio.sleep(pause)
            timing.first_output()
        timing.mark("posted")
        return line

    async def scenario():
        return await asyncio.gather(one("summary", 0.02), one("idiom_select", 0.01))

    first, second = asyncio.run(scenario())
    assert [c.label for c in first.calls] == ["summary"] and [c.label for c in second.calls] == ["idiom_select"]
    assert [s[0] for s in first.steps] == [s[0] for s in second.steps] == ["received", "posted"]


# T132-P1-B ------------------------------------------------------------------------------

def test_the_idiom_command_path_writes_one_line(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    ctx = idiom_context(tmp_path, monkeypatch, 5, TalkingIdiom([FOUR, PICK]))
    message = idiom_event(ctx)
    message.created_at = datetime.now(UTC) - timedelta(milliseconds=150)

    async def scenario():
        try:
            await ctx.client.on_message(message)
        finally:
            await ctx.client.close()

    asyncio.run(scenario())
    [line] = records(caplog)
    assert (line["kind"], line["outcome"]) == ("idiom", "success")
    assert [s[0] for s in line["steps"]] == ["received", "admitted", "collected", "queued", "posted"]
    assert [c["call"] for c in line["codex"]] == ["idiom_candidates", "idiom_select"]
    assert 100 <= line["discord_delay_ms"] < 5000
    times = [s[1] for s in line["steps"]]
    assert times == sorted(times) and line["total_ms"] >= times[-1]
    metrics = json.loads(next(r.message for r in caplog.records if '"idiom_request"' in r.message))
    assert metrics["request_id"] == line["request_id"]
    text = " ".join(r.message for r in caplog.records if r.name == "yoyackbot.timing")
    assert "대화" not in text and "우왕좌왕" not in text and "합성" not in text


@pytest.mark.parametrize(("note", "calls"), [
    (None, ["summary", "candidates", "judge"]), ("평가 빼줘", ["summary"]),
])
def test_the_summary_workflow_writes_one_line(tmp_path, monkeypatch, caplog, note, calls) -> None:
    caplog.set_level(logging.INFO)
    runner = Talking([f"{BODY}\n\n{OWN}"], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 3"])

    async def scenario():
        workflow, channel, lease, _ratings = workflow_context(tmp_path, monkeypatch, runner)
        request = SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1)),
                                 scope=describe_range("", settings(tmp_path)), request_note=note)
        await workflow.run(request, channel, lease, AsyncMock())
        await workflow.run(request, channel, lease, AsyncMock())  # the cooldown answer

    asyncio.run(scenario())
    first, second = records(caplog)
    assert first["outcome"] == "success" and [c["call"] for c in first["codex"]] == calls
    assert [s[0] for s in first["steps"]] == [
        "received", "admitted", "start_notice", "collected", "queued", "posted"]
    assert all(ordered(c) and c["result"] == "ok" for c in first["codex"])
    assert (second["outcome"], second["codex"], [s[0] for s in second["steps"]]) == ("cooldown", [], ["received"])
    assert first["request_id"] != second["request_id"]


def test_labels_are_allowlisted() -> None:
    line = timing.Timeline()
    line.mark("received")
    line.mark("내용이 들어간 단계")
    line.calls.append(timing.CodexCall("내용", 1, line, 2, 3, "ok"))
    payload = line.payload("다른 종류", "r", "success")
    assert payload["steps"] == [["received", 0]] and payload["kind"] == "unknown"
    assert payload["codex"][0]["call"] == "unknown"


def test_the_table_script_reads_a_journal(capsys, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("show_timings", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    line = {"event": "request_timing", "request_id": "abc", "kind": "summary", "outcome": "success",
            "discord_delay_ms": 120, "steps": [["received", 0], ["collected", 40], ["posted", 30000]],
            "codex": [{"n": 1, "call": "summary", "start": 50, "first_output": 4000, "end": 15000, "result": "ok"},
                      {"n": 2, "call": "summary_retry", "start": 15010, "first_output": None, "end": 29000,
                       "result": "ok"}],
            "total_ms": 30010}
    journal = ["INFO 다른 줄", "INFO " + json.dumps(line)]
    monkeypatch.setattr("sys.stdin", journal)
    monkeypatch.setattr("sys.argv", ["show_timings.py"])
    module.main()
    out = capsys.readouterr().out
    assert "summary abc · success · Discord 지연 120ms · 총 30,010ms" in out
    assert "Codex #1 summary 첫 출력  [시작 +3,950]" in out and "Codex #2 summary_retry (재시도) 완료(ok)" in out
    assert out.index("메시지 조회 완료") < out.index("Codex #1 summary 시작") < out.index("게시 완료")
