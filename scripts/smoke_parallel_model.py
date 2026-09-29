"""Run four synthetic, isolated model summaries on a test LXC only."""

import asyncio
import json
import time
from datetime import UTC, datetime

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import SandboxedCodex
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import InputWorkspace


class TimedRunner:
    def __init__(self, actual: SandboxedCodex) -> None:
        self.actual = actual
        self.contract = actual.contract
        self.active = 0
        self.peak = 0

    async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            return await self.actual.execute(workspace, prompt)
        finally:
            self.active -= 1


async def main() -> None:
    settings = Settings.from_environment()
    if settings.codex_concurrency != 4:
        raise ValueError("This smoke requires the four-call setting")
    actual = CodexSummaryEngine.from_settings(settings)
    timed = TimedRunner(actual.runner)
    engine = CodexSummaryEngine(settings, timed)  # type: ignore[arg-type]
    names = ("가람", "나래", "다온", "라온")
    started = time.monotonic()

    async def request(index: int, name: str) -> str:
        messages = [MessageRecord(
            index, 1, index + 10, index, name,
            f"{name}은 합성 병렬 시험에서 {index}번 자료를 내일 검토하겠다고 했소.",
            datetime(2026, 9, 29, tzinfo=UTC),
        )]
        result = await engine.summarize(messages, channel_name=f"합성 채널 {index}")
        return result.text

    summaries = await asyncio.gather(*(
        request(index, name) for index, name in enumerate(names, start=1)
    ))
    if timed.peak != 4 or any(
        name not in result or any(other in result for other in names if other != name)
        for name, result in zip(names, summaries, strict=True)
    ):
        raise AssertionError("Parallel summary isolation or concurrency failed")
    print(json.dumps({
        "calls": len(summaries), "peak_model_calls": timed.peak,
        "isolated": True, "elapsed_ms": round((time.monotonic() - started) * 1000),
    }, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
