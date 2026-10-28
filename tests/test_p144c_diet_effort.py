"""1.4.4c-P1: the diet review and the weekly advice always run at medium (T144c-P1-A)."""

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from test_codex_runner import runner as sandbox_runner

from yoyackbot.codex import DIET_MODEL, REQUIRED_MODEL, CodexFailure
from yoyackbot.codex_engine import MEDIUM_EFFORT_CALLS, CodexSummaryEngine
from yoyackbot.codex_runner import _EFFORT, _MODEL, CodexRunError
from yoyackbot.config import Settings
from yoyackbot.input_files import InputWorkspace

DATA = b'{"type":"person","person":"P1"}\n'


@dataclass(frozen=True)
class Runner:
    """Records each call's (model, effort); fails on the models in `failing` with a model error."""

    contract: object
    calls: list = field(default_factory=list)
    failing: frozenset = frozenset()
    timeout_seconds: float = 120

    async def execute(self, workspace, prompt):
        model = _MODEL.get() or REQUIRED_MODEL
        self.calls.append((model, _EFFORT.get() or self.contract.reasoning_effort))
        workspace.close()
        if model in self.failing:
            raise CodexRunError(CodexFailure.MODEL)
        return "answer"


def engine(tmp_path, configured, **runner):
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_INPUT_DIR": str(tmp_path / "in")})
    fake = Runner(SimpleNamespace(reasoning_effort=configured), **runner)
    return CodexSummaryEngine(settings, fake), fake.calls


@pytest.mark.parametrize("configured", ["low", "medium"])
def test_the_diet_calls_run_at_medium_whatever_the_setting(tmp_path, configured) -> None:
    built, calls = engine(tmp_path, configured)

    async def scenario():
        await built.diet_review("지시", DATA, [(b"photo", ".jpg")])
        await built.diet_advice("지시", DATA)

    asyncio.run(scenario())
    assert calls == [(DIET_MODEL, "medium"), (DIET_MODEL, "medium")]
    assert MEDIUM_EFFORT_CALLS == {"diet", "diet_week"}


@pytest.mark.parametrize("configured", ["low", "medium"])
def test_the_luna_fallback_stays_at_medium(tmp_path, configured) -> None:
    built, calls = engine(tmp_path, configured, failing=frozenset({DIET_MODEL}))
    asyncio.run(built.diet_advice("지시", DATA))
    assert calls == [(DIET_MODEL, "medium"), (REQUIRED_MODEL, "medium")]


@pytest.mark.parametrize(("configured", "expected"), [
    ("low", {"summary": "low", "candidates": "low", "self_roast": "low", "judge": "low",
             "idiom_select": "low", "notices": "high", "diet": "medium", "diet_week": "medium"}),
    ("medium", {"summary": "medium", "candidates": "medium", "self_roast": "medium", "judge": "low",
                "idiom_select": "low", "notices": "high", "diet": "medium", "diet_week": "medium"}),
])
def test_every_effort_rule(tmp_path, configured, expected) -> None:
    built, calls = engine(tmp_path, configured)

    async def scenario():
        for label in expected:
            await built._execute(label, InputWorkspace.create(tmp_path / "in", b"{}\n", inline=True), "지시")

    asyncio.run(scenario())
    assert dict(zip(expected, (effort for _model, effort in calls), strict=True)) == expected


def test_the_command_carries_medium(tmp_path) -> None:
    """The real sandbox command for a diet call says Terra at medium even when the setting is low."""
    isolated = sandbox_runner(tmp_path)                       # configured effort: low
    seen = []

    @dataclass(frozen=True)
    class Recording:
        contract: object
        timeout_seconds: float = 120

        async def execute(self, workspace, prompt):
            seen.append(isolated.command(workspace))
            workspace.close()
            return "answer"

    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_INPUT_DIR": str(tmp_path / "in")})
    built = CodexSummaryEngine(settings, Recording(isolated.contract))
    asyncio.run(built.diet_advice("지시", DATA))
    args = seen[0]
    assert args[args.index("--model") + 1] == DIET_MODEL
    assert "model_reasoning_effort=medium" in args and "model_reasoning_effort=low" not in args
