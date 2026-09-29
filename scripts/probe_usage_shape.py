"""Read the bot account's usage once and print only the response shape, never values or secrets.

Run as the service account on the development LXC:
    python scripts/probe_usage_shape.py <codex executable> <auth.json> <private work directory>
"""

import asyncio
import json
import sys
from pathlib import Path

from yoyackbot import usage

KEPT_VALUES = {"limitId", "windowDurationMins"}
KEYED_BY_ID = {"rateLimitsByLimitId"}


def shape(value: object, key: str | None = None) -> object:
    if isinstance(value, dict):
        return {
            name: shape(item, name if key not in KEYED_BY_ID else "bucket")
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    if key in KEPT_VALUES:
        return value
    return type(value).__name__


def main() -> int:
    executable, auth_file, work_root = sys.argv[1:4]
    parse = usage.parse_rate_limits
    seen: dict[str, object] = {}

    def recording_parse(result: object) -> usage.UsageSnapshot:
        seen["shape"] = shape(result)
        return parse(result)

    usage.parse_rate_limits = recording_parse
    try:
        snapshot = asyncio.run(
            usage.read_account_usage(executable, Path(auth_file), Path(work_root))
        )
        outcome = f"parsed warning={snapshot.warning}"
    except usage.UsageUnavailable as error:
        outcome = f"unavailable: {error}"
    print(json.dumps({"outcome": outcome, "shape": seen.get("shape")}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
