"""1.4.4b-P1: the diet review and the weekly advice on GPT-6.1 Terra, the rest on Luna (T144b-P1-A)."""

import asyncio
import logging
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_codex_runner import runner as sandbox_runner

from yoyackbot.codex import DIET_MODEL, REQUIRED_MODEL, CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import _MODEL, CodexRunError, call_model
from yoyackbot.config import Settings
from yoyackbot.input_files import InputWorkspace
from yoyackbot.notice_writer import rewrite_notices

DATA = b'{"type":"person","person":"P1"}\n'


def model_of(args: list[str]) -> str:
    return args[args.index("--model") + 1]


def test_the_command_takes_the_call_model(tmp_path) -> None:
    isolated = sandbox_runner(tmp_path)

    async def command(model):
        async with call_model(model):
            with InputWorkspace.create(tmp_path / "inputs", b"{}\n", inline=True) as workspace:
                return isolated.command(workspace)

    assert model_of(asyncio.run(command(None))) == REQUIRED_MODEL
    assert model_of(asyncio.run(command(DIET_MODEL))) == "gpt-6.1-terra"
    assert model_of(asyncio.run(command("gpt-6.1-sol"))) == REQUIRED_MODEL   # not allowed: ignored
    assert _MODEL.get() is None                                                 # nothing leaks out


@dataclass(frozen=True)
class Runner:
    """Records each call's model and images; fails on the models in `failing` with `kind`."""

    contract: object
    calls: list = field(default_factory=list)
    failing: frozenset = frozenset()
    kind: CodexFailure = CodexFailure.MODEL
    timeout_seconds: float = 120

    async def execute(self, workspace, prompt):
        model = _MODEL.get() or REQUIRED_MODEL
        self.calls.append((model, [p.read_bytes() for p in workspace.images], self.timeout_seconds))
        workspace.close()
        if model in self.failing:
            raise CodexRunError(self.kind)
        return f"answer from {model}"


def engine(tmp_path, **runner):
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_INPUT_DIR": str(tmp_path / "in")})
    fake = Runner(SimpleNamespace(reasoning_effort="medium"), **runner)
    return CodexSummaryEngine(settings, fake), fake.calls


def test_only_the_diet_calls_run_on_terra(tmp_path) -> None:
    built, calls = engine(tmp_path)

    async def scenario():
        await built.diet_review("지시", DATA, [(b"photo", ".jpg")])
        await built.diet_advice("지시", DATA)
        await built.rewrite_notices("지시", DATA)
        await rewrite_notices("서버 말투", built.rewrite_notices, keys=["diet.week_failed"])
        await built.self_roast([], "지시")

    asyncio.run(scenario())
    assert [model for model, _images, _timeout in calls] == [DIET_MODEL, DIET_MODEL] + [REQUIRED_MODEL] * 3
    assert calls[0][1:] == ([b"photo"], 300) and calls[1][1:] == ([], 120)


@pytest.mark.parametrize("call", ["review", "advice"])
def test_a_model_error_falls_back_to_luna_once(tmp_path, caplog, call) -> None:
    built, calls = engine(tmp_path, failing=frozenset({DIET_MODEL}))
    work = (built.diet_review("지시", DATA, [(b"photo", ".jpg")]) if call == "review"
            else built.diet_advice("지시", DATA))
    assert asyncio.run(work) == f"answer from {REQUIRED_MODEL}"
    assert [model for model, _images, _timeout in calls] == [DIET_MODEL, REQUIRED_MODEL]
    if call == "review":                                       # the photos are attached again
        assert calls[0][1] == calls[1][1] == [b"photo"] and calls[1][2] == 300
    assert f"codex_model_fallback call={'diet' if call == 'review' else 'diet_week'}" in caplog.text


@pytest.mark.parametrize("kind", [CodexFailure.LIMIT, CodexFailure.USAGE_LIMIT, CodexFailure.TIMEOUT,
                                  CodexFailure.OUTPUT_INVALID])
def test_other_failures_do_not_fall_back(tmp_path, caplog, kind) -> None:
    built, calls = engine(tmp_path, failing=frozenset({DIET_MODEL}), kind=kind)
    with pytest.raises(CodexRunError) as raised:
        asyncio.run(built.diet_advice("지시", DATA))
    assert raised.value.kind is kind and [c[0] for c in calls] == [DIET_MODEL]
    assert "codex_model_fallback" not in caplog.text


def test_luna_failing_too_reaches_the_caller(tmp_path) -> None:
    built, calls = engine(tmp_path, failing=frozenset({DIET_MODEL, REQUIRED_MODEL}))
    with pytest.raises(CodexRunError):
        asyncio.run(built.diet_review("지시", DATA, []))
    assert [c[0] for c in calls] == [DIET_MODEL, REQUIRED_MODEL]


def test_the_review_keeps_judging_with_the_fallback(tmp_path, caplog) -> None:
    """The 22:30 review through the client path still posts when only Luna answers."""
    from test_p143_diet_judge import GOOD, post

    from yoyackbot.diet_judge import judge_day

    caplog.set_level(logging.INFO)
    built, calls = engine(tmp_path, failing=frozenset({DIET_MODEL}))

    async def ask(prompt, diet):
        await built.diet_review(prompt, diet.data, diet.photos)
        return GOOD

    channel = SimpleNamespace(send=AsyncMock())
    outcome = asyncio.run(judge_day(1, channel, [], [post(501, "샐러드"), post(502, "라면", minutes=1)],
                                    tone=None, ask=ask))
    assert outcome == "posted" and [c[0] for c in calls] == [DIET_MODEL, REQUIRED_MODEL]
    assert "샐러드" not in caplog.text
