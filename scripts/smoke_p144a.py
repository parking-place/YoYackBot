"""T144a-P1-B: every Codex call kind through a given CLI build, on synthetic data (LXC only).

Runs the bot's own engine with `--executable`/`--host` (a staged CLI and code-mode host), so the
service's files are untouched. Prints one JSON line per call kind: pass/fail, the timing record
(first output, tokens, tool runs) and short synthetic answers. Nothing is posted.
"""

import argparse
import asyncio
import dataclasses
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_p144

from yoyackbot import self_roast, timing
from yoyackbot.codex import pin_executable
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, SummaryMode
from yoyackbot.notice_writer import rewrite_notices
from yoyackbot.tone_presets import BY_KEY
from yoyackbot.usage import UsageUnavailable, read_account_usage

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/summary_modes.json"


def records(fixture_id: str) -> list[MessageRecord]:
    fixture = next(f for f in json.loads(FIXTURES.read_text()) if f["id"] == fixture_id)
    people: dict[str, int] = {}
    return [MessageRecord(index, 1, 1, people.setdefault(key, len(people) + 1), name, body,
                          datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index))
            for index, (key, name, body, *_flags) in enumerate(fixture["messages"], start=1)]


async def timed(kind: str, work) -> dict:
    timeline = timing.begin()
    out: dict = {"kind": kind}
    try:
        out["result"] = await work()
        out["ok"] = True
    except (CodexRunError, UsageUnavailable, ValueError) as exc:
        out["ok"] = False
        out["error"] = getattr(getattr(exc, "kind", None), "value", type(exc).__name__)
    out["codex"] = timeline.payload("summary", "smoke", "ok")["codex"]
    return out


async def main_async(executable: str, host: str) -> None:
    settings = pin_executable(Settings.from_environment())
    settings = dataclasses.replace(settings, codex_executable=executable)
    engine = CodexSummaryEngine.from_settings(settings)          # checks the pinned version
    engine = dataclasses.replace(engine, runner=dataclasses.replace(engine.runner, code_mode_host=Path(host)))
    debate, triage = records("release_debate"), records("bug_triage")

    async def summary(fast: bool, rows):
        result = await engine.summarize(rows, channel_name="합성 평가 채널", mode=SummaryMode.SHORT, fast=fast)
        return {"chars": len(result.text), "rating": result.rating, "head": result.text[:120]}

    async def idiom():
        result = await engine.idiom(debate, channel_name="합성 평가 채널")
        return str(result)[:160]

    async def roast():
        answer = await engine.self_roast(debate[:6], self_roast.self_roast_prompt(None),
                                         channel_name="합성 평가 채널")
        text = self_roast.clean_answer(answer)
        return {"text": text[:160], "problem": self_roast.problem(text)}

    async def notices():
        result = await rewrite_notices(BY_KEY["mz"].tone, engine.rewrite_notices,
                                       keys=["diet.week_header", "diet.week_failed", "diet.estimate_note"])
        if result.failed_calls or len(result.table) != 3:
            raise ValueError(f"notices failed_calls={result.failed_calls} written={len(result.table)}")
        return result.table

    async def diet():
        out = await evaluate_p144.daily("default", None, engine)
        if "checks" not in out:
            raise ValueError("diet review failed")
        return {"checks": out["checks"], "attempts": len(out["attempts"])}

    async def week():
        out = await evaluate_p144.weekly("default", None, engine)
        if "checks" not in out:
            raise ValueError("weekly advice failed")
        return {"checks": out["checks"], "attempts": len(out["attempts"])}

    async def usage():
        snapshot = await read_account_usage(executable, settings.codex_auth_directory / "auth.json",
                                            settings.input_directory.absolute(), client_version="1.4.4.1")
        return str(snapshot)

    for kind, work in (("usage", usage), ("summary", lambda: summary(False, debate)),
                       ("summary_fast", lambda: summary(True, triage)), ("idiom", idiom),
                       ("self_roast", roast), ("notices_high", notices), ("diet_review", diet),
                       ("diet_week", week), ("usage_after", usage)):
        print(json.dumps(await timed(kind, work), ensure_ascii=False, default=str), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True)
    parser.add_argument("--host", required=True)
    args = parser.parse_args()
    asyncio.run(main_async(args.executable, args.host))


if __name__ == "__main__":
    main()
