"""B05: one channel's retry-state failure never ends the collection worker (T120-P3-A/B)."""

import asyncio
import json
import logging
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import discord
import pytest

from yoyackbot.__main__ import main
from yoyackbot.backfill import BackfillError, BackfillPageScheduler, BackfillState, RetryHolds
from yoyackbot.discord import YoYackClient
from yoyackbot.health import read_heartbeat_details, write_heartbeat

PRIVATE = "비밀 원문 private detail"


def state(channel_id: int, *, guild_id: int = 1) -> BackfillState:
    return BackfillState(
        guild_id, channel_id, f"token-{channel_id}", False, 1, 0, 10**18, "history",
        None, None, None, None, 0, None, None, None, None, None,
    )


class Store:
    """Synchronous like the SQLite store; every call is dispatched through to_thread."""

    def __init__(self, *channel_ids: int) -> None:
        self.states = [state(channel_id) for channel_id in channel_ids]
        self.pending_errors: list[BaseException] = []
        self.defer_failures: dict[int, int] = {}
        self.block_failures: dict[int, int] = {}
        self.deferred: list[int] = []
        self.blocked: list[tuple[int, str]] = []

    def pending(self, _now: datetime) -> tuple[BackfillState, ...]:
        if self.pending_errors:
            raise self.pending_errors.pop(0)
        blocked = {channel_id for channel_id, _ in self.blocked}
        return tuple(item for item in self.states if item.channel_id not in blocked)

    def _fail(self, failures: dict[int, int], channel_id: int, action: str) -> None:
        if failures.get(channel_id, 0):
            failures[channel_id] -= 1
            raise BackfillError(f"Unable to {action}: {PRIVATE}")

    def defer(self, item: BackfillState, *, until: datetime) -> None:
        self._fail(self.defer_failures, item.channel_id, "defer")
        self.deferred.append(item.channel_id)

    def block(self, item: BackfillState, *, reason: str) -> bool:
        self._fail(self.block_failures, item.channel_id, "block")
        self.blocked.append((item.channel_id, reason))
        return True


def harness(monkeypatch, store: Store, step: Callable, *, inaccessible: frozenset[int] = frozenset()):
    client = YoYackClient(clock=lambda: datetime.now(UTC))
    channels = {}
    for item in store.states:
        channel = Mock(spec=discord.TextChannel)
        channel.id = item.channel_id
        channel.guild = SimpleNamespace(id=item.guild_id)
        channels[item.channel_id] = channel
    monkeypatch.setattr(client, "get_channel", channels.get)
    monkeypatch.setattr(
        "yoyackbot.discord.valid_channel", lambda _guild, channel_id: channel_id not in inaccessible,
    )
    calls: dict[int, int] = {}

    async def page(channel, item, *, can_continue):
        calls[channel.id] = calls.get(channel.id, 0) + 1
        return await step(channel.id, calls[channel.id])

    client.backfill_store = store
    client.initial_backfill = SimpleNamespace(step=page)
    client.backfill_notifier = SimpleNamespace()
    client.backfill_scheduler = BackfillPageScheduler()
    client.backfill_holds = RetryHolds(first_seconds=0.2, max_seconds=0.4)
    client.backfill_retry_seconds = (0.02, 0.05)
    client.backfill_restart_seconds = (0.02, 0.05)
    client.ready_event.set()
    return client, calls


async def until(condition: Callable[[], bool], *, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


async def stop(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def ok(_channel_id: int, _call: int) -> bool:
    return True


@pytest.mark.parametrize("failure", ["page_then_defer", "unexpected_then_defer", "inaccessible"])
def test_defer_failure_holds_only_that_channel(monkeypatch, caplog, failure) -> None:
    caplog.set_level(logging.INFO)

    async def step(channel_id: int, _call: int) -> bool:
        if channel_id == 10 and failure == "page_then_defer":
            raise BackfillError(f"History page unavailable {PRIVATE}")
        if channel_id == 10 and failure == "unexpected_then_defer":
            raise RuntimeError(PRIVATE)
        return True

    async def scenario() -> None:
        store = Store(10, 11)
        store.defer_failures[10] = 1_000
        client, calls = harness(
            monkeypatch, store, step,
            inaccessible=frozenset({10}) if failure == "inaccessible" else frozenset(),
        )
        task = asyncio.create_task(client._backfill_loop())
        await until(lambda: calls.get(11, 0) >= 20)
        assert not task.done()
        assert client.collection_worker == "running"
        assert len(client.backfill_holds) == 1
        # Held by bounded backoff instead of being retried on every 50 ms tick.
        assert calls.get(10, 0) <= 3
        await stop(task)

    asyncio.run(scenario())
    assert "initial_backfill_state_write_failed action=defer" in caplog.text
    if failure == "unexpected_then_defer":
        assert "initial_backfill_page_failed kind=unexpected" in caplog.text
    assert PRIVATE not in caplog.text


def test_permanent_block_failure_retries_after_backoff_then_records(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)

    async def step(channel_id: int, _call: int) -> bool:
        if channel_id == 10:
            raise BackfillError(PRIVATE, retryable=False, kind="permission")
        return True

    async def scenario() -> None:
        store = Store(10, 11)
        store.block_failures[10] = 2
        client, calls = harness(monkeypatch, store, step)
        task = asyncio.create_task(client._backfill_loop())
        await until(lambda: store.blocked == [(10, "permission")])
        assert len(client.backfill_holds) == 0
        assert calls[10] == 3 and calls[11] >= 3
        assert not task.done()
        await stop(task)

    asyncio.run(scenario())
    assert caplog.text.count("initial_backfill_state_write_failed action=block") == 2
    assert "initial_backfill_blocked kind=permission" in caplog.text
    assert PRIVATE not in caplog.text


def test_database_recovery_resumes_and_clears_the_hold(monkeypatch) -> None:
    async def step(channel_id: int, call: int) -> bool:
        if channel_id == 10 and call <= 2:
            raise BackfillError("History page unavailable")
        return True

    async def scenario() -> None:
        store = Store(10)
        store.defer_failures[10] = 1
        client, calls = harness(monkeypatch, store, step)
        task = asyncio.create_task(client._backfill_loop())
        await until(lambda: store.deferred == [10])
        # First defer failed (held); the retry after backoff persisted the delay.
        assert len(client.backfill_holds) == 0
        await until(lambda: calls[10] >= 4)
        assert not task.done()
        await stop(task)

    asyncio.run(scenario())


def test_shared_state_outage_backs_off_and_resumes(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        store = Store(11)
        store.pending_errors = [BackfillError(PRIVATE) for _ in range(3)]
        client, calls = harness(monkeypatch, store, ok)
        seen = set()
        sleep = asyncio.sleep

        async def watch_sleep(delay: float) -> None:
            seen.add((client.collection_worker, delay))
            await sleep(delay)

        monkeypatch.setattr("yoyackbot.discord.asyncio.sleep", watch_sleep)
        task = asyncio.create_task(client._backfill_loop())
        await until(lambda: calls.get(11, 0) >= 2)
        assert {("backoff", 0.02), ("backoff", 0.04), ("backoff", 0.05)} <= seen
        assert client.collection_worker == "running"
        await stop(task)

    asyncio.run(scenario())
    assert caplog.text.count("initial_backfill_state_unavailable") == 3
    assert PRIVATE not in caplog.text


def test_supervisor_restarts_an_unexpected_loop_exit_without_duplicates(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> None:
        store = Store(11)
        store.pending_errors = [ValueError(PRIVATE)]
        client, calls = harness(monkeypatch, store, ok)
        loops = {"active": 0, "max": 0}
        original = client._backfill_loop

        async def counted() -> None:
            loops["active"] += 1
            loops["max"] = max(loops["max"], loops["active"])
            try:
                await original()
            finally:
                loops["active"] -= 1

        monkeypatch.setattr(client, "_backfill_loop", counted)
        client._backfill_task = asyncio.create_task(client._supervise_backfill())
        await until(lambda: calls.get(11, 0) >= 2)
        assert client.collection_restarts == 1
        assert client.collection_worker_state() == "running"
        assert loops == {"active": 1, "max": 1}
        await stop(client._backfill_task)
        assert client.collection_worker == "stopped"
        assert loops["active"] == 0

    asyncio.run(scenario())
    assert "backfill_worker_restarting failures=1" in caplog.text
    assert PRIVATE not in caplog.text


def test_close_propagates_cancellation_and_releases_page_slots(monkeypatch) -> None:
    cancelled: list[int] = []

    async def scenario() -> None:
        started = asyncio.Event()

        async def step(channel_id: int, _call: int) -> bool:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(channel_id)
                raise
            return True

        store = Store(10)
        client, _calls = harness(monkeypatch, store, step)
        client._backfill_task = asyncio.create_task(client._supervise_backfill())
        await started.wait()
        scheduler = client.backfill_scheduler
        assert scheduler.global_limit._value == 2
        task = client._backfill_task
        await client.close()
        assert task.cancelled()
        assert cancelled == [10]
        assert scheduler.global_limit._value == 3
        assert scheduler.guild_limits[1]._value == 2
        assert client.collection_worker == "stopped"
        assert store.deferred == []

    asyncio.run(scenario())


def test_worker_state_never_reports_a_dead_or_stuck_loop_as_collecting(monkeypatch) -> None:
    async def scenario() -> None:
        client = YoYackClient()
        assert client.collection_worker_state() == "disabled"
        client.backfill_store = Store()
        assert client.collection_worker_state() == "stopped"

        async def crash() -> None:
            raise RuntimeError(PRIVATE)

        client._backfill_task = asyncio.create_task(crash())
        await asyncio.gather(client._backfill_task, return_exceptions=True)
        assert client.collection_worker_state() == "failed"
        client._backfill_task = asyncio.create_task(asyncio.Event().wait())
        client.collection_worker = "running"
        client._collection_tick = time.monotonic()
        assert client.collection_worker_state() == "running"
        client._collection_tick -= 901
        assert client.collection_worker_state() == "stalled"
        client.collection_worker = "waiting"
        assert client.collection_worker_state() == "waiting"
        client._backfill_task.cancel()
        await asyncio.gather(client._backfill_task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize(("worker", "ready"), [
    ("running", True), ("waiting", True), ("disabled", True), ("backoff", False),
    ("restarting", False), ("stalled", False), ("failed", False), ("stopped", False), (None, False),
])
def test_health_requires_a_collecting_worker(tmp_path, monkeypatch, capsys, worker, ready) -> None:
    root = tmp_path / "input"
    write_heartbeat(root, gateway_ready=True, collection_worker=worker or "running")
    if worker is None:
        # An older writer without the field is unknown, never assumed healthy.
        path = root / "gateway-health.json"
        payload = json.loads(path.read_text())
        del payload["collection_worker"]
        path.write_text(json.dumps(payload))
    assert read_heartbeat_details(root)[2] == worker
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "synthetic")
    monkeypatch.setenv("YOYACK_DB_PATH", str(tmp_path / "health.db"))
    monkeypatch.setenv("YOYACK_INPUT_DIRECTORY", str(root))
    monkeypatch.setattr("yoyackbot.__main__.check_ready", lambda _settings: None)
    monkeypatch.setattr(sys, "argv", ["yoyackbot", "health"])
    code = main()
    report = json.loads(capsys.readouterr().out)
    assert report["collection_worker"] == (worker or "unknown")
    assert report["gateway_ready"] is True
    assert report["ready"] is ready
    assert code == (0 if ready else 2)
    with pytest.raises(ValueError):
        write_heartbeat(root, gateway_ready=True, collection_worker=PRIVATE)
