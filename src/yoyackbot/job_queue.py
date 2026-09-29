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


@dataclass(eq=False)
class _Ticket:
    guild_id: int | None
    size_hint: int | None
    bypasses: int = 0


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
    def __init__(self, *, concurrency: int = 1, capacity: int = 8, wait_seconds: float = 420) -> None:
        if concurrency < 1 or capacity < 0 or wait_seconds <= 0:
            raise ValueError("Invalid model queue limits")
        self.concurrency = concurrency
        self.capacity = capacity
        self.wait_seconds = wait_seconds
        self._running = 0
        self._waiters: deque[_Ticket] = deque()
        self._closed = False
        self._condition = asyncio.Condition()
        self._last_guild: int | None = None

    def _next_waiter(self) -> _Ticket:
        oldest = self._waiters[0]
        if oldest.size_hint is None:
            return oldest
        for ticket in self._waiters:
            if ticket.bypasses >= 2:
                return ticket
        candidates = [ticket for ticket in self._waiters if ticket.size_hint is not None]
        if len(candidates) != len(self._waiters):
            return oldest
        other_guild = [ticket for ticket in candidates if ticket.guild_id != self._last_guild]
        if self._last_guild is not None and other_guild:
            candidates = other_guild
        return min(candidates, key=lambda ticket: ticket.size_hint or 0)

    async def acquire(
        self, *, guild_id: int | None = None, size_hint: int | None = None,
    ) -> QueueLease:
        if guild_id is not None and guild_id < 1:
            raise ValueError("guild_id must be positive")
        if size_hint is not None and size_hint < 1:
            raise ValueError("size_hint must be positive")
        async with self._condition:
            if self._closed:
                raise QueueClosed
            if self._running < self.concurrency and not self._waiters:
                self._running += 1
                self._last_guild = guild_id
                return QueueLease(self)
            if len(self._waiters) >= self.capacity:
                raise QueueFull
            ticket = _Ticket(guild_id, size_hint)
            self._waiters.append(ticket)
            try:
                try:
                    async with asyncio.timeout(self.wait_seconds):
                        while not self._closed and (
                            self._next_waiter() is not ticket or self._running >= self.concurrency
                        ):
                            await self._condition.wait()
                except TimeoutError as exc:
                    raise QueueWaitExpired from exc
                if self._closed:
                    raise QueueClosed
                for waiting in self._waiters:
                    if waiting is not ticket:
                        waiting.bypasses += 1
                self._waiters.remove(ticket)
                self._running += 1
                self._last_guild = guild_id
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
