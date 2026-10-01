"""Call the pinned model on synthetic fixtures; print output for human review only."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, SummaryMode
from yoyackbot.parser import clean_request_note
from yoyackbot.summary_prompt import PROMPT_VERSION


def records(fixture: dict[str, object]) -> list[MessageRecord]:
    people: dict[str, int] = {}
    items: list[MessageRecord] = []
    for index, row in enumerate(fixture["messages"], start=1):  # type: ignore[index]
        key, name, body, *flags = row
        author_id = people.setdefault(key, len(people) + 1)
        items.append(MessageRecord(
            message_id=index, guild_id=1, channel_id=1, author_id=author_id,
            author_name=name, content=body,
            created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(minutes=index),
            has_attachment=bool(flags[0]) if flags else False,
        ))
    return items


async def evaluate(
    first: int, count: int, fixture_name: str, mode: SummaryMode, note: str | None = None,
) -> None:
    fixtures = json.loads(
        (Path(__file__).resolve().parents[1] / "tests/fixtures" / fixture_name).read_text()
    )
    settings = Settings.from_environment()
    engine = CodexSummaryEngine.from_settings(settings)
    for fixture in fixtures[first:first + count]:
        try:
            result = await engine.summarize(
                records(fixture), channel_name="합성 평가 채널", mode=mode, request_note=note,
            )
            outcome = {"id": fixture["id"], "prompt": PROMPT_VERSION, "mode": mode.value,
                       "note": note, "rating": result.rating, "ongoing": result.ongoing_jab,
                       "model": result.model, "text": result.text}
        except Exception as exc:  # noqa: BLE001 - keep diagnostics free of prompt/auth contents
            outcome = {"id": fixture["id"], "prompt": PROMPT_VERSION,
                       "error_type": type(exc).__name__}
            if isinstance(exc, CodexRunError):
                outcome["error_kind"] = exc.kind.value
        print(json.dumps(outcome, ensure_ascii=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=int, default=0)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--fixtures", default="summary_quality.json",
                        choices=("summary_quality.json", "summary_modes.json"))
    parser.add_argument("--mode", default="short", choices=[mode.value for mode in SummaryMode])
    parser.add_argument("--note", default=None, help="request note, cleaned like a Discord command")
    args = parser.parse_args()
    if args.first < 0 or args.count < 1:
        parser.error("--first must be nonnegative and --count positive")
    note = clean_request_note(args.note) if args.note else None
    asyncio.run(evaluate(args.first, args.count, args.fixtures, SummaryMode(args.mode), note))


if __name__ == "__main__":
    main()
