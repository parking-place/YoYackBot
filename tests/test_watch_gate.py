"""Unwatched channels cannot reach ingestion or summarization work."""

import asyncio
from unittest.mock import AsyncMock

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.watch_gate import UNWATCHED_NOTICE, GateResult, WatchGate


def test_unwatched_never_calls_expensive_or_persistent_adapters() -> None:
    async def scenario() -> None:
        store = MemoryWatchStore()
        gate = WatchGate(store)
        cache = AsyncMock()
        history = AsyncMock()
        cli = AsyncMock()
        cooldown = AsyncMock()
        publish = AsyncMock()
        notice = AsyncMock()
        help_reply = AsyncMock()
        unavailable = AsyncMock()

        assert await gate.ingest(1, 10, object(), cache) is GateResult.UNWATCHED

        async def summarize(lease) -> None:
            await history()
            await cli()
            await cooldown()
            await publish()

        result = await gate.request(
            1,
            10,
            is_help=False,
            help_reply=help_reply,
            unwatched_reply=notice,
            unavailable_reply=unavailable,
            summarize=summarize,
        )
        assert result is GateResult.UNWATCHED
        notice.assert_awaited_once_with(UNWATCHED_NOTICE)
        for spy in (cache, history, cli, cooldown, publish):
            spy.assert_not_awaited()

        assert await gate.request(
            1,
            10,
            is_help=True,
            help_reply=help_reply,
            unwatched_reply=notice,
            unavailable_reply=unavailable,
            summarize=summarize,
        ) is GateResult.HELP
        help_reply.assert_awaited_once()

    asyncio.run(scenario())


def test_add_remove_and_version_change_invalidate_inflight_work() -> None:
    async def scenario() -> None:
        store = MemoryWatchStore()
        gate = WatchGate(store)
        cache = AsyncMock()
        store.replace(1, frozenset({10}))
        result, lease = gate.lease(1, 10)
        assert result is GateResult.ACCEPTED
        assert lease is not None and lease.valid()
        assert await gate.ingest(1, 10, object(), cache) is GateResult.ACCEPTED
        cache.assert_awaited_once()

        store.replace(1, frozenset())
        assert not lease.valid()
        assert await gate.ingest(1, 10, object(), cache) is GateResult.UNWATCHED
        cache.assert_awaited_once()
        store.replace(1, frozenset({10}))
        assert gate.lease(1, 10)[1] is not None
        assert not lease.valid()
        assert gate.lease(2, 10)[0] is GateResult.UNWATCHED

    asyncio.run(scenario())


def test_settings_read_failure_fails_closed() -> None:
    class BrokenStore(MemoryWatchStore):
        def get(self, guild_id: int) -> frozenset[int]:
            raise OSError("synthetic database failure")

    async def scenario() -> None:
        gate = WatchGate(BrokenStore())
        cache = AsyncMock()
        assert await gate.ingest(1, 10, object(), cache) is GateResult.UNAVAILABLE
        cache.assert_not_awaited()
        unavailable = AsyncMock()
        summary = AsyncMock()
        assert await gate.request(
            1,
            10,
            is_help=False,
            help_reply=AsyncMock(),
            unwatched_reply=AsyncMock(),
            unavailable_reply=unavailable,
            summarize=summary,
        ) is GateResult.UNAVAILABLE
        unavailable.assert_awaited_once()
        summary.assert_not_awaited()

    asyncio.run(scenario())
