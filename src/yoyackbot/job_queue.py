"""Bounded FIFO admission for expensive model processes."""

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Self


class QueueFull(RuntimeError):
    """The finite model wait queue has no room."""


class QueueWaitExpired(RuntimeError):
    """A waiting request exceeded its configured limit."""


class QueueClosed(RuntimeError):
    """The gateway is shutting down and cannot start new model work."""


@dataclass
class QueueLease:
    queue: "SummaryJobQueue"
    released: bool = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_error: object) -> None:
        if not self.released:
            await self.queue.release()
            self.released = True


class SummaryJobQueue:
    def __init__(self, *, concurrency: int = 1, capacity: int = 4, wait_seconds: float = 60) -> None:
        if concurrency < 1 or capacity < 0 or wait_seconds <= 0:
            raise ValueError("Invalid model queue limits")
        self.concurrency = concurrency
        self.capacity = capacity
        self.wait_seconds = wait_seconds
        self._running = 0
        self._waiters: deque[object] = deque()
        self._closed = False
        self._condition = asyncio.Condition()

    async def acquire(self) -> QueueLease:
        async with self._condition:
            if self._closed:
                raise QueueClosed
            if self._running < self.concurrency and not self._waiters:
                self._running += 1
                return QueueLease(self)
            if len(self._waiters) >= self.capacity:
                raise QueueFull
            ticket = object()
            self._waiters.append(ticket)
            try:
                try:
                    async with asyncio.timeout(self.wait_seconds):
                        while not self._closed and (
                            self._waiters[0] is not ticket or self._running >= self.concurrency
                        ):
                            await self._condition.wait()
                except TimeoutError as exc:
                    raise QueueWaitExpired from exc
                if self._closed:
                    raise QueueClosed
                assert self._waiters.popleft() is ticket
                self._running += 1
                self._condition.notify_all()
                return QueueLease(self)
            except BaseException:
                if ticket in self._waiters:
                    self._waiters.remove(ticket)
                    self._condition.notify_all()
                raise

    async def release(self) -> None:
        async with self._condition:
            if self._running < 1:
                raise RuntimeError("No model slot is held")
            self._running -= 1
            self._condition.notify_all()

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    async def snapshot(self) -> tuple[int, int, bool]:
        async with self._condition:
            return self._running, len(self._waiters), self._closed
