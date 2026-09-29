"""Eight-hour bounded synthetic workload and real service sampler (LXC only)."""

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord

from yoyackbot import workflow as workflow_module
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import CollectionOutcome
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.domain import (
    MessageRecord,
    PublicationReceipt,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.health import read_heartbeat
from yoyackbot.job_queue import SummaryJobQueue
from yoyackbot.message_store import CacheFailureKind, MessageStoreError, SQLiteMessageStore
from yoyackbot.state import ChannelStates, ChannelStatus
from yoyackbot.workflow import QUEUE_FULL_NOTICE, SummaryWorkflow

SERVICE = "yoyackbot-dev.service"
REPO = Path("/opt/yoyackbot-dev")
LIMITS = {
    "rss_bytes": 512 * 1024 * 1024,
    "cgroup_bytes": 768 * 1024 * 1024,
    "cpu_percent": 200,
    "tasks": 32,
    "db_growth_bytes": 20 * 1024 * 1024,
    "journal_bytes": 50 * 1024 * 1024,
    "unexpected_restarts": 1,
}


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL).strip()


def _journal_size() -> int:
    output = command("journalctl", "--namespace=yoyackbot-dev", "--disk-usage")
    match = re.search(r"([\d.]+)([KMGT]?)\b", output)
    if match is None:
        raise RuntimeError("Journal size is unavailable")
    return int(float(match.group(1)) * 1024 ** {"": 0, "K": 1, "M": 2, "G": 3, "T": 4}[match.group(2)])


def service_sample(input_root: Path, db_path: Path, previous_cpu: int | None,
                   elapsed_since_last: float) -> dict[str, int | float | bool]:
    props = command(
        "systemctl", "show", SERVICE, "-p", "MainPID", "-p", "MemoryCurrent",
        "-p", "CPUUsageNSec", "-p", "TasksCurrent", "-p", "NRestarts", "-p", "ActiveState",
    )
    values = dict(line.split("=", 1) for line in props.splitlines())
    def number(key: str) -> int:
        try:
            return int(values[key])
        except (KeyError, ValueError):
            return 0

    pid = number("MainPID")
    rss = 0
    if pid > 0:
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            match = re.search(r"^VmRSS:\s+(\d+)", status, re.MULTILINE)
            rss = int(match.group(1)) * 1024 if match else 0
        except OSError:
            pass
    cpu_ns = number("CPUUsageNSec")
    cpu_percent = 0.0 if previous_cpu is None or elapsed_since_last <= 0 else (
        max(0, cpu_ns - previous_cpu) / (elapsed_since_last * 1_000_000_000) * 100
    )
    alive, gateway = read_heartbeat(input_root)
    return {
        "ready": values["ActiveState"] == "active" and alive and gateway,
        "rss_bytes": rss,
        "cgroup_bytes": number("MemoryCurrent"),
        "cpu_ns": cpu_ns,
        "cpu_percent": round(cpu_percent, 2),
        "tasks": number("TasksCurrent"),
        "restart_count": number("NRestarts"),
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "journal_bytes": _journal_size(),
        "request_dirs": len(list(input_root.glob("request-*"))),
    }


class Collector:
    def __init__(self, *, full: bool = False) -> None:
        self.full = full

    async def collect(self, _channel, *, guild_id, channel_id, request, **_kwargs):
        if self.full:
            raise MessageStoreError("synthetic full", kind=CacheFailureKind.FULL)
        record = MessageRecord(
            1, guild_id, channel_id, 1, "합성", "합성 자원 시험",
            request.accepted_at - timedelta(minutes=1),
        )
        return CollectionOutcome((record,), 0, request.accepted_at, 0, False, 1, 0)


class Engine:
    def __init__(self, *, timeout: bool = False, gate: asyncio.Event | None = None) -> None:
        self.timeout = timeout
        self.gate = gate

    async def summarize(self, *_args, **_kwargs):
        if self.gate is not None:
            await self.gate.wait()
        if self.timeout:
            raise CodexRunError(CodexFailure.TIMEOUT)
        await asyncio.sleep(0.005)
        return SummaryResult("합성 요약이오.", "synthetic", 1)


class Publisher:
    async def publish(self, *_args, **_kwargs):
        return PublicationReceipt((1,), datetime.now(UTC))


def request(channel_id: int) -> tuple[SummaryRequest, object]:
    now = datetime.now(UTC)
    item = SummaryRequest(
        1, channel_id, 1,
        RangeRequest(RequestKind.TIME, now, start=now - timedelta(minutes=5)),
    )
    channel = SimpleNamespace(
        type=discord.ChannelType.text, id=channel_id,
        guild=SimpleNamespace(id=1), name="합성",
    )
    return item, channel


async def exercise(workflow: SummaryWorkflow, channel_id: int) -> list[str]:
    notices: list[str] = []

    async def notice(value: str) -> None:
        notices.append(value)

    item, channel = request(channel_id)
    await workflow.run(item, channel, SimpleNamespace(valid=lambda: True), notice)
    assert await workflow.states.status(1, channel_id) is not ChannelStatus.SUMMARIZING
    return notices


async def fault_drill(root: Path, number: int) -> None:
    for collector, engine in ((Collector(full=True), Engine()), (Collector(), Engine(timeout=True))):
        workflow = SummaryWorkflow(collector, engine, Publisher(), ChannelStates())
        assert await exercise(workflow, 2000 + number)  # User sees a safe failure notice.
        assert await workflow.states.status(1, 2000 + number) is ChannelStatus.IDLE
    gate = asyncio.Event()
    workflow = SummaryWorkflow(
        Collector(), Engine(gate=gate), Publisher(), ChannelStates(),
        SummaryJobQueue(concurrency=1, capacity=4, wait_seconds=5),
    )
    jobs = [asyncio.create_task(exercise(workflow, 3000 + number * 10 + index))
            for index in range(5)]
    for _ in range(200):
        if await workflow.queue.snapshot() == (1, 4, False):
            break
        await asyncio.sleep(0.01)
    assert await workflow.queue.snapshot() == (1, 4, False)
    overflow = await exercise(workflow, 3999 + number)
    assert overflow == [QUEUE_FULL_NOTICE]
    gate.set()
    await asyncio.gather(*jobs)
    assert await workflow.queue.snapshot() == (0, 0, False)
    await workflow.shutdown()

    store = SQLiteMessageStore(root / "ttl.db")
    now = datetime.now(UTC)
    old = MessageRecord(1, 1, 1, 1, "합성", "오래된 합성", now - timedelta(days=8))
    current = MessageRecord(2, 1, 1, 1, "합성", "현재 합성", now - timedelta(days=1))
    store.upsert(old, cached_at=now)
    store.upsert(current, cached_at=now)
    assert store.prune_before(now - timedelta(days=7)) >= 1
    with sqlite3.connect(root / "ttl.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


async def model_probe() -> bool:
    process = await asyncio.create_subprocess_exec(
        "runuser", "-u", "yoyackbot-dev", "--", "bash", "-c",
        "set -a; . /var/lib/yoyackbot-dev/secrets.env; set +a; "
        "cd /opt/yoyackbot-dev; /opt/yoyackbot-dev/.venv/bin/python "
        "scripts/soak_080_model_probe.py",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(process.wait(), timeout=180) == 0
    except TimeoutError:
        process.kill()
        await process.wait()
        return False


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=28800)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()
    if args.duration_seconds < 1 or args.interval_seconds < 1:
        raise ValueError("Soak durations must be positive")
    args.report_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(args.report_dir, 0o700)
    logging.getLogger("yoyackbot.metrics").disabled = True
    workflow_module.valid_channel = lambda _guild, _id: True
    assert command("git", "-C", str(REPO), "rev-parse", "HEAD") == args.expected_sha
    db_initial = args.db.stat().st_size
    started_at = datetime.now(UTC).isoformat()
    manifest = args.report_dir / "manifest.json"
    manifest.write_text(json.dumps({
        "start_utc": started_at,
        "expected_sha": args.expected_sha,
        "duration_seconds": args.duration_seconds,
        "interval_seconds": args.interval_seconds,
        "limits": LIMITS,
        "test_mode": args.test_mode,
        "db_initial_bytes": db_initial,
    }, indent=2, sort_keys=True) + "\n")
    manifest.chmod(0o600)
    synthetic = SummaryWorkflow(
        Collector(), Engine(), Publisher(),
        ChannelStates(SQLiteCooldownStore(args.report_dir / "state.db")),
        SummaryJobQueue(concurrency=1, capacity=4, wait_seconds=5),
    )
    samples: list[dict] = []
    probes: list[asyncio.Task[bool]] = []
    probe_marks = [0, 10800, 28740]
    restarted = False
    failures: list[str] = []
    start = time.monotonic()
    previous_time = start
    previous_cpu: int | None = None
    next_tick = start
    tick = 0
    samples_file = args.report_dir / "samples.jsonl"
    try:
        with samples_file.open("x", encoding="utf-8") as stream:
            os.chmod(samples_file, 0o600)
            while time.monotonic() - start < args.duration_seconds:
                elapsed = time.monotonic() - start
                if command("git", "-C", str(REPO), "rev-parse", "HEAD") != args.expected_sha:
                    failures.append("sha_changed")
                    break
                if not args.test_mode and not restarted and elapsed >= 14400:
                    await asyncio.to_thread(
                        subprocess.run, ["systemctl", "restart", SERVICE], check=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    restarted = True
                if not args.test_mode:
                    for index, mark in enumerate(probe_marks):
                        if elapsed >= mark and len(probes) == index:
                            probes.append(asyncio.create_task(model_probe()))
                notices = await exercise(synthetic, 1 + tick % 6)
                if not notices:
                    assert await exercise(synthetic, 1 + tick % 6)
                if tick % 15 == 0:
                    await fault_drill(args.report_dir, tick)
                now = time.monotonic()
                sample = service_sample(args.input_root, args.db, previous_cpu, now - previous_time)
                sample.update({
                    "timestamp_utc": datetime.now(UTC).isoformat(),
                    "sha": args.expected_sha,
                    "elapsed_seconds": round(now - start, 3),
                    "synthetic_cycle": tick + 1,
                })
                stream.write(json.dumps(sample, separators=(",", ":")) + "\n")
                stream.flush()
                samples.append(sample)
                previous_cpu = int(sample["cpu_ns"])
                previous_time = now
                tick += 1
                next_tick += args.interval_seconds
                await asyncio.sleep(max(0, next_tick - time.monotonic()))
    except Exception as exc:  # noqa: BLE001
        failures.append(type(exc).__name__)
    duration = time.monotonic() - start
    probe_results = await asyncio.gather(*probes)
    await synthetic.shutdown()
    final_queue = await synthetic.queue.snapshot()
    with sqlite3.connect(args.db) as connection:
        cutoff = int((datetime.now(UTC) - timedelta(days=7)).timestamp() * 1_000_000)
        expired = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at_us<?", (cutoff,)
        ).fetchone()[0]
    raw_backups = sum(
        len(list(root.glob("*.db"))) for root in (
            args.db.parent / "backups", args.db.parent.parent / "backups"
        )
    )
    aggregate = {
        "sha": args.expected_sha,
        "start_utc": started_at,
        "end_utc": datetime.now(UTC).isoformat(),
        "duration_seconds": round(duration, 3),
        "samples": len(samples),
        "synthetic_cycles": tick,
        "model_probes": len(probe_results),
        "model_probe_passes": sum(probe_results),
        "planned_restart": restarted,
        "ready_ratio": sum(bool(s["ready"]) for s in samples) / max(1, len(samples)),
        "max_rss_bytes": max((int(s["rss_bytes"]) for s in samples), default=0),
        "max_cgroup_bytes": max((int(s["cgroup_bytes"]) for s in samples), default=0),
        "max_cpu_percent": max((float(s["cpu_percent"]) for s in samples), default=0),
        "max_tasks": max((int(s["tasks"]) for s in samples), default=0),
        "max_db_growth_bytes": max((int(s["db_bytes"]) - db_initial for s in samples), default=0),
        "max_journal_bytes": max((int(s["journal_bytes"]) for s in samples), default=0),
        "max_unexpected_restarts": max((int(s["restart_count"]) for s in samples), default=0),
        "final_request_dirs": len(list(args.input_root.glob("request-*"))),
        "final_queue_running": final_queue[0],
        "final_queue_waiting": final_queue[1],
        "raw_backup_count": raw_backups,
        "expired_messages": expired,
        "failures": failures,
    }
    aggregate["eligible"] = bool(
        not args.test_mode and duration >= 28800 and len(samples) >= 460 and tick >= 460
        and restarted and len(probe_results) == sum(probe_results) == 3
        and aggregate["ready_ratio"] >= 0.99 and aggregate["final_request_dirs"] == 0
        and aggregate["expired_messages"] == 0 and raw_backups == 0
        and final_queue[:2] == (0, 0)
        and aggregate["max_rss_bytes"] <= LIMITS["rss_bytes"]
        and aggregate["max_cgroup_bytes"] <= LIMITS["cgroup_bytes"]
        and aggregate["max_cpu_percent"] <= LIMITS["cpu_percent"]
        and aggregate["max_tasks"] <= LIMITS["tasks"]
        and aggregate["max_db_growth_bytes"] <= LIMITS["db_growth_bytes"]
        and aggregate["max_journal_bytes"] <= LIMITS["journal_bytes"]
        and aggregate["max_unexpected_restarts"] <= LIMITS["unexpected_restarts"]
        and not failures
    )
    summary = args.report_dir / "summary.json"
    summary.write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n")
    summary.chmod(0o600)
    print(json.dumps({"eligible": aggregate["eligible"], "samples": len(samples),
                      "duration_seconds": round(duration), "report_saved": True}))
    return 0 if aggregate["eligible"] or args.test_mode else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
