"""Finite FIFO model queue with timeout, cancellation, and shutdown."""

import asyncio

import pytest

from yoyackbot.job_queue import QueueClosed, QueueFull, QueueWaitExpired, SummaryJobQueue


def test_fifo_capacity_and_global_concurrency_are_enforced() -> None:
    async def scenario() -> None:
        queue = SummaryJobQueue(concurrency=1, capacity=2, wait_seconds=2)
        first = await queue.acquire()
        order: list[str] = []
        release_a, release_b = asyncio.Event(), asyncio.Event()

        async def waiting(name: str, release: asyncio.Event) -> None:
            async with await queue.acquire():
                order.append(name)
                await release.wait()

        a = asyncio.create_task(waiting("a", release_a))
        await asyncio.sleep(0)
        b = asyncio.create_task(waiting("b", release_b))
        await asyncio.sleep(0)
        assert await queue.snapshot() == (1, 2, False)
        with pytest.raises(QueueFull):
            await queue.acquire()
        await first.__aexit__(None, None, None)
        await asyncio.wait_for(_until(lambda: order == ["a"]), 2)
        assert await queue.snapshot() == (1, 1, False)
        release_a.set()
        await asyncio.wait_for(_until(lambda: order == ["a", "b"]), 2)
        release_b.set()
        await asyncio.gather(a, b)
        assert await queue.snapshot() == (0, 0, False)

    asyncio.run(scenario())


async def _until(predicate) -> None:
    while not predicate():
        await asyncio.sleep(0.001)


def test_timeout_cancellation_and_close_never_leave_waiters() -> None:
    async def scenario() -> None:
        timed = SummaryJobQueue(concurrency=1, capacity=1, wait_seconds=0.03)
        timed_first = await timed.acquire()
        with pytest.raises(QueueWaitExpired):
            await timed.acquire()
        assert await timed.snapshot() == (1, 0, False)
        await timed_first.__aexit__(None, None, None)

        queue = SummaryJobQueue(concurrency=1, capacity=1, wait_seconds=2)
        first = await queue.acquire()

        waiting = asyncio.create_task(queue.acquire())
        await asyncio.wait_for(_until_queue_waiters(queue, 1), 2)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert await queue.snapshot() == (1, 0, False)

        waiting = asyncio.create_task(queue.acquire())
        await asyncio.wait_for(_until_queue_waiters(queue, 1), 2)
        await queue.close()
        with pytest.raises(QueueClosed):
            await waiting
        with pytest.raises(QueueClosed):
            await queue.acquire()
        await first.__aexit__(None, None, None)
        assert await queue.snapshot() == (0, 0, True)

    asyncio.run(scenario())


async def _until_queue_waiters(queue: SummaryJobQueue, wanted: int) -> None:
    while (await queue.snapshot())[1] != wanted:
        await asyncio.sleep(0.001)
