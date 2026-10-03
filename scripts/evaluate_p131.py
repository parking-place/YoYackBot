"""T131-P4: the pinned model in the standard and the fast tier on the same synthetic inputs (LXC only).

Prints one JSON line per run for human review; nothing is posted. Each input runs standard, then
fast, so both tiers see the same load. The runner records whether every call carried the tier.
"""

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_p130 import ROOT, idiom_selection, kind_of, records

from yoyackbot.codex import FAST_SERVICE_TIER, PINNED_CLI_VERSION
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.domain import SummaryMode
from yoyackbot.idiom import IdiomFailed
from yoyackbot.input_files import InputWorkspace
from yoyackbot.output_quality import narrator_uses_hate_term
from yoyackbot.rating_pool import banned_angle
from yoyackbot.summary_prompt import PROMPT_VERSION

TIER = f'service_tier="{FAST_SERVICE_TIER}"'


class Recorder:
    def __init__(self, engine: CodexSummaryEngine) -> None:
        self.calls: list[dict] = []
        runner = engine.runner
        execute = runner.execute

        async def counted(workspace: InputWorkspace, prompt: str) -> str:
            entry = {"kind": kind_of(prompt), "tier": TIER in runner.command(workspace)}
            self.calls.append(entry)
            started = time.monotonic()
            try:
                return await execute(workspace, prompt)
            finally:
                entry["ms"] = round((time.monotonic() - started) * 1000)

        object.__setattr__(runner, "execute", counted)


async def summaries(engine: CodexSummaryEngine, recorder: Recorder, ids: list[str]) -> None:
    fixtures = {f["id"]: f for f in json.loads((ROOT / "summary_modes.json").read_text())}
    for fixture_id in ids:
        for fast in (False, True):
            recorder.calls.clear()
            started = time.monotonic()
            rows = records(fixtures[fixture_id])
            out = {"id": fixture_id, "kind": "summary", "fast": fast, "prompt": PROMPT_VERSION,
                   "cli": PINNED_CLI_VERSION, "effort": engine.runner.contract.reasoning_effort}
            try:
                result = await engine.summarize(rows, channel_name="합성 평가 채널", mode=SummaryMode.SHORT,
                                                fast=fast)
                out.update(ok=True, rating=result.rating, chars=len(result.text),
                           banned_angle=bool(result.rating_text) and banned_angle(result.rating_text),
                           hate=narrator_uses_hate_term(result.text), text=result.text)
            except CodexRunError as exc:
                out.update(ok=False, error_kind=exc.kind.value)
            out.update(ms=round((time.monotonic() - started) * 1000), calls=len(recorder.calls),
                       call_kinds=[c["kind"] for c in recorder.calls],
                       call_ms=[c.get("ms") for c in recorder.calls],
                       tier_on_every_call=all(c["tier"] == fast for c in recorder.calls))
            print(json.dumps(out, ensure_ascii=False), flush=True)


async def idioms(engine: CodexSummaryEngine, recorder: Recorder) -> None:
    cases = json.loads((ROOT / "idiom_cases.json").read_text())
    with tempfile.TemporaryDirectory(dir=engine.settings.input_directory.absolute()) as directory:
        for case in cases:
            selected, _total = idiom_selection(case, Path(directory))
            for fast in (False, True):
                recorder.calls.clear()
                started = time.monotonic()
                out = {"id": case["id"], "kind": "idiom", "fast": fast}
                try:
                    result = await engine.idiom(selected, channel_name="합성 평가 채널", fast=fast)
                    out.update(ok=True, text=result.text, selected_kind=result.selected_kind)
                except (IdiomFailed, CodexRunError) as exc:
                    out.update(ok=False, error=type(exc).__name__)
                out.update(ms=round((time.monotonic() - started) * 1000), calls=len(recorder.calls),
                           call_ms=[c.get("ms") for c in recorder.calls],
                           tier_on_every_call=all(c["tier"] == fast for c in recorder.calls))
                print(json.dumps(out, ensure_ascii=False), flush=True)


async def main_async(which: str, ids: list[str]) -> None:
    engine = CodexSummaryEngine.from_settings(Settings.from_environment())
    recorder = Recorder(engine)
    if which in ("all", "summaries"):
        await summaries(engine, recorder, ids)
    if which in ("all", "idioms"):
        await idioms(engine, recorder)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("which", choices=("all", "summaries", "idioms"))
    parser.add_argument("--ids", nargs="*", default=["release_debate", "bug_triage", "multi_topic_group"])
    args = parser.parse_args()
    asyncio.run(main_async(args.which, args.ids))


if __name__ == "__main__":
    main()
