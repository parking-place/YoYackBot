"""1.3.3-P4: the summary and the rating candidates run at the same time (T133-P4-A/B)."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from rating_fakes import candidates, is_candidates, is_judge
from test_p130_rating_judge import BODY, NOW, OWN, ROWS, TEN, Runner, settings, workflow_context

from yoyackbot import timing
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine, ModelSlots
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.domain import RangeRequest, RequestKind, SummaryRequest
from yoyackbot.output_quality import RATING_LABEL


class Slow(Runner):
    """Each call takes `pause` seconds; records (kind, start, end) on a shared clock."""

    def __init__(self, *args, pause=0.05, fail_summary=False, cands_pause=None) -> None:
        super().__init__(*args)
        self.pause = pause
        self.cands_pause = cands_pause
        self.fail_summary = fail_summary
        self.spans: list[tuple[str, float, float | None]] = []
        self.cancelled: list[str] = []

    async def execute(self, workspace, prompt):
        kind = "cands" if is_candidates(prompt) else "judge" if is_judge(prompt) else "summary"
        loop = asyncio.get_running_loop()
        index = len(self.spans)
        self.spans.append((kind, loop.time(), None))
        try:
            await asyncio.sleep(self.cands_pause if kind == "cands" and self.cands_pause else self.pause)
        except asyncio.CancelledError:
            self.cancelled.append(kind)
            workspace.close()
            raise
        self.spans[index] = (kind, self.spans[index][1], loop.time())
        if kind == "summary" and self.fail_summary:
            workspace.close()
            raise CodexRunError(CodexFailure.TIMEOUT)
        return await super().execute(workspace, prompt)


def engine_for(tmp_path, runner, concurrency="4"):
    return CodexSummaryEngine(settings(tmp_path, YOYACK_CODEX_CONCURRENCY=concurrency), runner)  # type: ignore[arg-type]


def leftovers(tmp_path):
    return list((tmp_path / "in").glob("request-*"))


# T133-P4-A ------------------------------------------------------------------------------

def test_candidates_start_with_the_summary_and_the_judge_waits_for_both(tmp_path) -> None:
    runner = Slow([f"{BODY}\n\n{OWN}"], [candidates(*TEN)], ["비슷함: 없음\n선택: 3"], pause=0.2)
    engine = engine_for(tmp_path, runner)

    async def scenario():
        line = timing.begin()
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await engine.summarize(ROWS)
        return result, loop.time() - started, line

    result, took, line = asyncio.run(scenario())
    (s_kind, _s_start, s_end), (c_kind, c_start, c_end), (j_kind, j_start, _) = runner.spans
    assert (s_kind, c_kind, j_kind) == ("summary", "cands", "judge")
    assert c_start < s_end and j_start >= max(s_end, c_end)
    assert took < 2.75 * runner.pause              # two calls overlapped: about 2 pauses, not 3
    assert (result.rating, result.rating_text) == ("picked", RATING_LABEL + TEN[2])
    labels = [c.label for c in line.calls]
    assert labels == ["summary", "candidates", "judge"] and line.calls[1].start_ms - line.calls[0].start_ms < 30
    assert engine._slots.busy == 0 and not leftovers(tmp_path)


@pytest.mark.parametrize(("summaries", "cands", "judges", "status", "kinds"), [
    ([BODY], ["형식 없음", "형식 없음"], [], "missing", ["summary", "cands", "cands"]),
    ([f"{BODY}\n\n{OWN}"], [CodexRunError(CodexFailure.TIMEOUT)], [], "fallback_summary", ["summary", "cands"]),
    ([BODY], [candidates(*TEN[:2]), candidates(TEN[8])], ["비슷함: 1, 2\n선택: 없음"], "regenerated",
     ["summary", "cands", "judge", "cands"]),
    (["- **__P1__**: 라면을 꺼냈소.", BODY], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 1"], "picked",
     ["summary", "cands", "summary", "judge"]),
])
def test_every_rating_outcome_and_the_call_cap(tmp_path, summaries, cands, judges, status, kinds) -> None:
    runner = Slow(summaries, cands, judges)
    result = asyncio.run(engine_for(tmp_path, runner).summarize(ROWS))
    assert result.rating == status and [s[0] for s in runner.spans] == kinds and len(runner.spans) <= 5
    assert result.text.startswith(BODY)


def test_skipping_the_rating_makes_no_candidate_call(tmp_path) -> None:
    runner = Slow([f"{BODY}\n\n{OWN}"], [], [])
    engine = engine_for(tmp_path, runner)
    result = asyncio.run(engine.summarize(ROWS, request_note="평가 빼줘"))
    assert result.rating == "skipped" and [s[0] for s in runner.spans] == ["summary"] and engine._slots.busy == 0


def test_the_body_and_the_rating_are_posted_together(tmp_path, monkeypatch) -> None:
    runner = Slow([f"{BODY}\n\n{OWN}"], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 2"])

    async def scenario():
        workflow, channel, lease, _ratings = workflow_context(tmp_path, monkeypatch, runner)
        request = SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1)))
        await workflow.run(request, channel, lease, AsyncMock())
        return channel

    channel = asyncio.run(scenario())
    posts = [call.args[0] for call in channel.send.await_args_list]
    assert len(posts) == 1 and "야식 메뉴" in posts[0] and posts[0].rstrip().endswith(TEN[1])


# T133-P4-B ------------------------------------------------------------------------------

def test_a_failed_summary_cancels_the_candidates(tmp_path) -> None:
    runner = Slow([], [candidates(*TEN)], [], pause=0.05, fail_summary=True, cands_pause=5)
    engine = engine_for(tmp_path, runner)

    async def scenario():
        return await asyncio.gather(engine.summarize(ROWS), return_exceptions=True)

    [outcome] = asyncio.run(scenario())
    assert isinstance(outcome, CodexRunError)
    assert runner.cancelled == ["cands"] and engine._slots.busy == 0 and not leftovers(tmp_path)


def test_cancelling_the_request_cancels_both_calls(tmp_path) -> None:
    runner = Slow([BODY], [candidates(*TEN)], [], pause=5)
    engine = engine_for(tmp_path, runner)

    async def scenario():
        task = asyncio.create_task(engine.summarize(ROWS))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
    assert sorted(runner.cancelled) == ["cands", "summary"] and engine._slots.busy == 0
    assert not leftovers(tmp_path)


@pytest.mark.parametrize(("concurrency", "parallel"), [("1", False), ("2", False), ("3", True), ("4", True)])
def test_borrowing_needs_two_free_slots(tmp_path, concurrency, parallel) -> None:
    runner = Slow([BODY], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 1"])
    asyncio.run(engine_for(tmp_path, runner, concurrency).summarize(ROWS))
    (_s, _s_start, s_end), (_c, c_start, _c_end) = runner.spans[:2]
    assert (c_start < s_end) is parallel


def test_another_request_still_gets_a_slot_at_once() -> None:
    async def scenario():
        slots = ModelSlots(3)
        await slots.__aenter__()              # request A
        assert slots.try_borrow()             # A's candidates: 2 of 3 in use
        assert not slots.try_borrow()         # never down to zero free by borrowing
        loop = asyncio.get_running_loop()
        started = loop.time()
        await slots.__aenter__()              # request B enters without waiting
        waited = loop.time() - started
        assert slots.busy == 3
        for _ in range(3):
            slots.release()
        return waited, slots.busy

    waited, busy = asyncio.run(scenario())
    assert waited < 0.01 and busy == 0


def test_a_busy_engine_runs_the_calls_in_order(tmp_path) -> None:
    runner = Slow([BODY], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 1"])
    engine = engine_for(tmp_path, runner, "2")

    async def scenario():
        await engine._slots.__aenter__()      # another channel's request holds one of two slots
        try:
            await engine.summarize(ROWS)
        finally:
            engine._slots.release()

    asyncio.run(scenario())
    (_s, _s_start, s_end), (_c, c_start, _c_end) = runner.spans[:2]
    assert c_start >= s_end and engine._slots.busy == 0
