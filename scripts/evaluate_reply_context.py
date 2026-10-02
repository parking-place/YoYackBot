"""T120-P6-D: call the pinned model on the eight synthetic reply cases (LXC only).

Prints one JSON line per case for human review: output text, calls, latency and automatic
checks. Excluded messages stand for a target outside the range or deleted/filtered; their
reply keeps `reply: true` with no `reply_to`, exactly as the cache would send it.
"""

import argparse
import asyncio
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.codex import PINNED_CLI_VERSION
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, SummaryMode
from yoyackbot.input_files import message_keys
from yoyackbot.summary_prompt import PROMPT_VERSION

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/reply_context.json"
BASE = 1_400_000_000_000_000_000
KEY = re.compile(r"(?<![A-Za-z0-9])[MP][1-9][0-9]*(?![0-9])")


def records(case: dict) -> list[MessageRecord]:
    authors: dict[str, int] = {}
    items = []
    for index, row in enumerate(case["messages"], start=1):
        target = row.get("reply_to")
        items.append(MessageRecord(
            BASE + index * 1_000_000, 1, 1, authors.setdefault(row["speaker"], len(authors) + 1),
            row["name"], row["body"], datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index),
            is_reply=target is not None,
            reply_to_message_id=BASE + target * 1_000_000 if target is not None else None,
        ))
    excluded = {BASE + index * 1_000_000 for index in case.get("exclude", [])}
    return [item for item in items if item.message_id not in excluded]


async def evaluate(first: int, count: int) -> None:
    cases = json.loads(FIXTURE.read_text())
    engine = CodexSummaryEngine.from_settings(Settings.from_environment())
    calls = [0]
    execute = engine.runner.execute

    async def counted(workspace, prompt):
        calls[0] += 1
        return await execute(workspace, prompt)

    object.__setattr__(engine.runner, "execute", counted)
    for case in cases[first:first + count]:
        selected = records(case)
        keys = sorted(message_keys(selected).values())
        sources = " ".join(item.content for item in selected)
        calls[0] = 0
        started = time.monotonic()
        outcome = {"id": case["id"], "mode": case["mode"], "prompt": PROMPT_VERSION,
                   "cli": PINNED_CLI_VERSION, "keys_sent": keys, "check": case["check"]}
        try:
            result = await engine.summarize(
                selected, channel_name="합성 평가 채널", mode=SummaryMode(case["mode"]),
            )
            leaked = [key for key in KEY.findall(result.text) if key not in sources]
            outcome.update({
                "model": result.model, "rating": result.rating, "text": result.text,
                "key_leaks": leaked,
                "forbidden_hits": [word for word in case["forbidden"] if word in result.text],
            })
        except CodexRunError as exc:
            outcome["error_kind"] = exc.kind.value
        outcome.update(calls=calls[0], ms=round((time.monotonic() - started) * 1000))
        print(json.dumps(outcome, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=int, default=0)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()
    if args.first < 0 or args.count < 1:
        parser.error("--first must be nonnegative and --count positive")
    asyncio.run(evaluate(args.first, args.count))


if __name__ == "__main__":
    main()
