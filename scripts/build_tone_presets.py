"""Write the notices of the `/말투` presets (1.4.2) with gpt-6-luna at high; development only.

Usage: build_tone_presets.py OUT_JSON [--missing] [--only KEY ...]

With --missing, entries that already pass for the current catalog are kept and only the rest are
written. Entries that fail the checks are retried once; anything still failing keeps the default
text, so every preset covers the whole catalog. Prints one JSON line of counts per preset.
"""

import argparse
import asyncio
import json
from pathlib import Path

from yoyackbot.codex import pin_executable
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.notice_writer import rewrite_notices
from yoyackbot.notices import CATALOG, problem
from yoyackbot.tone_presets import PRESETS


def valid(table: dict) -> dict[str, str]:
    return {key: text for key, text in table.items()
            if key in CATALOG and isinstance(text, str) and problem(CATALOG[key], text) is None}


async def build(out: Path, *, missing: bool, only: set[str]) -> None:
    data = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    engine = CodexSummaryEngine.from_settings(pin_executable(Settings.from_environment()))
    for preset in PRESETS:
        if only and preset.key not in only:
            continue
        table = valid(data.get(preset.key, {})) if missing else {}
        wanted = [key for key in CATALOG if key not in table]
        calls = failed_calls = 0
        for _attempt in range(2):
            if not wanted:
                break
            result = await rewrite_notices(preset.tone, engine.rewrite_notices, keys=wanted)
            calls += 1
            failed_calls += result.failed_calls
            table.update(result.table)
            wanted = [key for key in CATALOG if key not in table]
        defaults = {key: CATALOG[key].text for key in wanted}
        table.update(defaults)
        data[preset.key] = {key: table[key] for key in CATALOG}
        print(json.dumps({"preset": preset.key, "entries": len(data[preset.key]),
                          "defaults": sorted(defaults), "rounds": calls,
                          "failed_calls": failed_calls}, ensure_ascii=False), flush=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--missing", action="store_true")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    asyncio.run(build(args.out, missing=args.missing, only=set(args.only)))


if __name__ == "__main__":
    main()
