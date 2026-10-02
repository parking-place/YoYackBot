"""T120-P3-D: bounded cache reads keep rows and peak RSS flat as the database grows (LXC only).

Each database holds one channel's synthetic rows over the same 20 hours, so the 10x database
only makes the requested range 10x denser. Databases are built by a separate invocation, and
every measurement runs in a fresh process with the same runtime and default SQLite settings.
"""

import argparse
import asyncio
import json
import math
import os
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord

from yoyackbot.backfill import SQLiteBackfillStore
from yoyackbot.cache_collector import CacheOnlyCollector
from yoyackbot.domain import RangeRequest, RequestKind
from yoyackbot.input_files import ConversationTooLarge
from yoyackbot.message_store import READ_BATCH_ROWS, SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
BUDGET = 4 * 1024 * 1024
BODY = b"x" * 256
SIZES = (100_000, 1_000_000)
RUNS = 3
TIMEOUT_SECONDS = 60
MEMORY_LIMIT = 512 * 1024 * 1024
DISK_LIMIT = 2 * 1024 * 1024 * 1024
MAX_ROWS = math.ceil(BUDGET / len(BODY)) + 2 * READ_BATCH_ROWS
MAX_PEAK_KIB = 256 * 1024
MAX_GROWTH_KIB = 32 * 1024


def build(path: Path, rows: int) -> None:
    if path.exists():
        raise SystemExit(f"{path} already exists")
    SQLiteWatchStore(path).replace(1, frozenset({2}))
    start = int((NOW - timedelta(hours=20)).timestamp() * 1_000_000)
    step = (20 * 3600 * 1_000_000) // rows
    body = BODY.decode()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, "
            "verified_us=?, finished_us=?", (int(NOW.timestamp() * 1_000_000),) * 3,
        )
        connection.executemany(
            "INSERT INTO messages(message_id, guild_id, channel_id, author_id, author_name, "
            "content, created_at_us, edited_at_us, cached_at_us, has_attachment, is_reply) "
            "VALUES (?, 1, 2, ?, '합성 화자', ?, ?, NULL, ?, 0, 0)",
            ((index + 1, 3 + index % 8, body, start + index * step, start)
             for index in range(rows)),
        )
    if path.stat().st_size > DISK_LIMIT:
        path.unlink()
        raise SystemExit("synthetic database exceeds the disk limit")


def _kib(field: str) -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    raise RuntimeError(field)


def measure(path: Path) -> dict:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))
    read = [0]

    class Counting(SQLiteMessageStore):
        def recent(self, *args, **kwargs):
            return super().recent(*args, on_rows=lambda n: read.__setitem__(0, read[0] + n),
                                  **kwargs)

    clock = lambda: NOW
    collector = CacheOnlyCollector(
        SQLiteWatchStore(path), Counting(path, clock=clock),
        SQLiteBackfillStore(path, clock=clock), max_content_bytes=BUDGET, clock=clock,
    )
    channel = SimpleNamespace(type=discord.ChannelType.text, id=2, guild=SimpleNamespace(id=1))
    request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(days=1))
    start_kib = _kib("VmRSS")
    began = time.monotonic()
    try:
        asyncio.run(collector.collect(channel, guild_id=1, channel_id=2, request=request))
        outcome = "selected"
    except ConversationTooLarge:
        outcome = "too_large"
    except MemoryError:
        outcome = "memory_limit"
    return {
        "outcome": outcome, "rows_read": read[0], "seconds": round(time.monotonic() - began, 3),
        "start_rss_kib": start_kib, "peak_rss_kib": _kib("VmHWM"),
    }


def run_all(directory: Path) -> int:
    results = []
    for rows in SIZES:
        path = directory / f"rows-{rows}.db"
        for attempt in range(1, RUNS + 1):
            try:
                done = subprocess.run(
                    [sys.executable, __file__, "measure", str(path)], capture_output=True,
                    text=True, timeout=TIMEOUT_SECONDS, check=False,
                )
                result = (json.loads(done.stdout) if done.returncode == 0
                          else {"outcome": f"exit_{done.returncode}"})
            except subprocess.TimeoutExpired:
                result = {"outcome": "timeout"}
            result.update(rows=rows, attempt=attempt, db_bytes=path.stat().st_size)
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    peaks = {rows: statistics.median(r.get("peak_rss_kib", math.inf) for r in results
                                     if r["rows"] == rows) for rows in SIZES}
    checks = {
        "all_too_large": all(r["outcome"] == "too_large" for r in results),
        "rows_read_max": max(r.get("rows_read", math.inf) for r in results),
        "rows_read_limit": MAX_ROWS,
        "peak_rss_max_kib": max(r.get("peak_rss_kib", math.inf) for r in results),
        "peak_rss_limit_kib": MAX_PEAK_KIB,
        "median_peak_kib": peaks,
        "median_growth_kib": peaks[SIZES[1]] - peaks[SIZES[0]],
        "median_growth_limit_kib": MAX_GROWTH_KIB,
        "sqlite_cache_size": sqlite3.connect(":memory:").execute("PRAGMA cache_size").fetchone()[0],
    }
    passed = (
        checks["all_too_large"] and checks["rows_read_max"] <= MAX_ROWS
        and checks["peak_rss_max_kib"] <= MAX_PEAK_KIB
        and checks["median_growth_kib"] <= MAX_GROWTH_KIB
    )
    print(json.dumps({"summary": checks, "pass": passed}, sort_keys=True, default=str))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["build", "measure", "run"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        args.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        for rows in SIZES:
            build(args.path / f"rows-{rows}.db", rows)
        print(json.dumps({rows: os.path.getsize(args.path / f"rows-{rows}.db") for rows in SIZES}))
        return 0
    if args.command == "measure":
        print(json.dumps(measure(args.path)))
        return 0
    return run_all(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
