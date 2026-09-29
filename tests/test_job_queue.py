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


def test_long_model_job_expires_under_old_wait_but_passes_with_180_second_policy() -> None:
    async def scenario(wait_seconds: float, *, expect_timeout: bool) -> None:
        # Scale 120 model seconds to 0.6 seconds, preserving the old/new ratio.
        queue = SummaryJobQueue(concurrency=1, capacity=1, wait_seconds=wait_seconds)
        first = await queue.acquire()
        follower = asyncio.create_task(queue.acquire())
        await asyncio.wait_for(_until_queue_waiters(queue, 1), 2)
        await asyncio.sleep(0.6)
        await first.__aexit__(None, None, None)
        if expect_timeout:
            with pytest.raises(QueueWaitExpired):
                await follower
        else:
            next_lease = await asyncio.wait_for(follower, 1)
            await next_lease.__aexit__(None, None, None)
        assert await queue.snapshot() == (0, 0, False)

    asyncio.run(scenario(0.3, expect_timeout=True))  # previous 60 seconds
    asyncio.run(scenario(0.9, expect_timeout=False))  # new 180 seconds


def test_cancelling_running_job_releases_slot_and_promotes_next_waiter() -> None:
    async def scenario() -> None:
        queue = SummaryJobQueue(concurrency=1, capacity=1, wait_seconds=2)
        started = asyncio.Event()

        async def running() -> None:
            async with await queue.acquire():
                started.set()
                await asyncio.Event().wait()

        first = asyncio.create_task(running())
        await asyncio.wait_for(started.wait(), 2)
        second = asyncio.create_task(queue.acquire())
        await asyncio.wait_for(_until_queue_waiters(queue, 1), 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        lease = await asyncio.wait_for(second, 2)
        await lease.__aexit__(None, None, None)
        assert await queue.snapshot() == (0, 0, False)

    asyncio.run(scenario())


async def _until_queue_waiters(queue: SummaryJobQueue, wanted: int) -> None:
    while (await queue.snapshot())[1] != wanted:
        await asyncio.sleep(0.001)


def test_short_jobs_and_other_guild_progress_without_starving_oldest() -> None:
    async def scenario(guilds: tuple[int, ...], expected: list[str]) -> None:
        queue = SummaryJobQueue(concurrency=1, capacity=4, wait_seconds=2)
        first = await queue.acquire(guild_id=1, size_hint=120)
        order: list[str] = []
        releases = {name: asyncio.Event() for name in ("long", "short1", "short2")}

        async def waiting(name: str, guild_id: int, size_hint: int) -> None:
            async with await queue.acquire(guild_id=guild_id, size_hint=size_hint):
                order.append(name)
                await releases[name].wait()

        jobs = []
        for index, (name, size) in enumerate((("long", 120), ("short1", 8), ("short2", 8))):
            jobs.append(asyncio.create_task(waiting(name, guilds[index], size)))
            await asyncio.wait_for(_until_queue_waiters(queue, index + 1), 2)

        await first.__aexit__(None, None, None)
        for index, name in enumerate(expected):
            await asyncio.wait_for(_until(lambda wanted=index + 1: len(order) == wanted), 2)
            assert order[index] == name
            releases[name].set()
        await asyncio.gather(*jobs)
        assert await queue.snapshot() == (0, 0, False)

    asyncio.run(scenario((1, 1, 2), ["short2", "short1", "long"]))
    asyncio.run(scenario((1, 1, 1), ["short1", "short2", "long"]))


def test_size_aware_queue_has_bounded_overtaking() -> None:
    async def scenario() -> None:
        queue = SummaryJobQueue(concurrency=1, capacity=4, wait_seconds=2)
        first = await queue.acquire(guild_id=1, size_hint=120)
        order: list[str] = []
        releases = {name: asyncio.Event() for name in ("long", "a", "b", "c")}

        async def waiting(name: str, size_hint: int) -> None:
            async with await queue.acquire(guild_id=1, size_hint=size_hint):
                order.append(name)
                await releases[name].wait()

        jobs = []
        for index, (name, size) in enumerate((("long", 120), ("a", 8), ("b", 8), ("c", 8))):
            jobs.append(asyncio.create_task(waiting(name, size)))
            await asyncio.wait_for(_until_queue_waiters(queue, index + 1), 2)
        await first.__aexit__(None, None, None)
        for index, name in enumerate(("a", "b", "long", "c")):
            await asyncio.wait_for(_until(lambda wanted=index + 1: len(order) == wanted), 2)
            assert order[index] == name
            releases[name].set()
        await asyncio.gather(*jobs)
        assert await queue.snapshot() == (0, 0, False)

    asyncio.run(scenario())
