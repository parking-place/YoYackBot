"""Atomic per-Guild/channel admission for summary jobs."""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from yoyackbot.cooldown import SQLiteCooldownStore


class ChannelStatus(Enum):
    IDLE = "idle"
    SUMMARIZING = "summarizing"
    COOLDOWN = "cooldown"


class AdmissionKind(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class Admission:
    kind: AdmissionKind
    remaining_seconds: int = 0


class ChannelStates:
    def __init__(
        self, cooldowns: SQLiteCooldownStore | None = None, *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.cooldowns = cooldowns
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self._active: set[tuple[int, int]] = set()
        self._deadline: dict[tuple[int, int], float] = {}
        self._expired: set[tuple[int, int]] = set()
        self._guard = asyncio.Lock()

    async def begin(self, guild_id: int, channel_id: int) -> bool:
        return (await self.admit(guild_id, channel_id)).kind is AdmissionKind.ACCEPTED

    async def admit(self, guild_id: int, channel_id: int) -> Admission:
        key = guild_id, channel_id
        async with self._guard:
            if key in self._active:
                return Admission(AdmissionKind.BUSY)
            remaining = await self._remaining_locked(key)
            if remaining > 0:
                return Admission(AdmissionKind.COOLDOWN, remaining)
            self._active.add(key)
            return Admission(AdmissionKind.ACCEPTED)

    async def _remaining_locked(self, key: tuple[int, int]) -> int:
        if self.cooldowns is None or key in self._expired:
            return 0
        if key in self._deadline:
            remaining = max(0, math.ceil(self._deadline[key] - self.monotonic()))
            if remaining == 0:
                del self._deadline[key]
                self._expired.add(key)
            return remaining
        remaining = await asyncio.to_thread(self.cooldowns.remaining, *key, self.clock())
        if remaining > 0:
            self._deadline[key] = self.monotonic() + remaining
        else:
            self._expired.add(key)
        return remaining

    async def finish_success(self, guild_id: int, channel_id: int, at: datetime) -> None:
        key = guild_id, channel_id
        async with self._guard:
            if self.cooldowns is not None:
                await asyncio.to_thread(self.cooldowns.record_success, guild_id, channel_id, at)
                expiry = at + timedelta(seconds=self.cooldowns.duration_seconds)
                remaining = min(self.cooldowns.duration_seconds, max(
                    0, math.ceil((expiry - self.clock()).total_seconds())
                ))
                self._expired.discard(key)
                if remaining > 0:
                    self._deadline[key] = self.monotonic() + remaining
                else:
                    self._deadline.pop(key, None)
                    self._expired.add(key)
            self._active.discard(key)

    async def finish(self, guild_id: int, channel_id: int) -> None:
        async with self._guard:
            self._active.discard((guild_id, channel_id))

    async def status(self, guild_id: int, channel_id: int) -> ChannelStatus:
        async with self._guard:
            if (guild_id, channel_id) in self._active:
                return ChannelStatus.SUMMARIZING
            if await self._remaining_locked((guild_id, channel_id)) > 0:
                return ChannelStatus.COOLDOWN
            return ChannelStatus.IDLE
