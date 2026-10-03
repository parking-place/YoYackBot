"""Atomic per-Guild/channel admission for summary jobs."""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.domain import SummaryMode
from yoyackbot.scope import RangeScope


class ChannelStatus(Enum):
    IDLE = "idle"
    SUMMARIZING = "summarizing"
    COOLDOWN = "cooldown"


class CooldownKind(Enum):
    """One channel slot is shared; the success cooldown is counted per command (1.3.1)."""

    SUMMARY = "summary"
    IDIOM = "idiom"


class AdmissionKind(Enum):
    ACCEPTED = "accepted"
    BUSY = "busy"
    COOLDOWN = "cooldown"


@dataclass(eq=False)
class ActiveJob:
    """The first admitted request's fixed scope; later requests only read it."""

    scope: RangeScope | None
    mode: SummaryMode = SummaryMode.SHORT
    announced: asyncio.Event = field(default_factory=asyncio.Event, repr=False)


@dataclass(frozen=True)
class Admission:
    kind: AdmissionKind
    remaining_seconds: int = 0
    job: ActiveJob | None = None


class ChannelStates:
    def __init__(
        self, cooldowns: SQLiteCooldownStore | None = None, *,
        idiom_cooldowns: SQLiteCooldownStore | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.cooldowns = cooldowns
        self._stores = {CooldownKind.SUMMARY: cooldowns, CooldownKind.IDIOM: idiom_cooldowns}
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self._active: dict[tuple[int, int], ActiveJob] = {}
        self._deadline: dict[tuple[CooldownKind, int, int], float] = {}
        self._expired: set[tuple[CooldownKind, int, int]] = set()
        self._guard = asyncio.Lock()

    async def begin(self, guild_id: int, channel_id: int) -> bool:
        return (await self.admit(guild_id, channel_id)).kind is AdmissionKind.ACCEPTED

    async def admit(
        self, guild_id: int, channel_id: int, *,
        scope: RangeScope | None = None, mode: SummaryMode = SummaryMode.SHORT,
        kind: CooldownKind = CooldownKind.SUMMARY,
    ) -> Admission:
        """Admit one job per channel; BUSY returns the running job's scope, never the new one."""
        key = guild_id, channel_id
        async with self._guard:
            active = self._active.get(key)
            if active is not None:
                return Admission(AdmissionKind.BUSY, job=active)
            remaining = await self._remaining_locked(key, kind)
            if remaining > 0:
                return Admission(AdmissionKind.COOLDOWN, remaining)
            job = ActiveJob(scope, mode)
            self._active[key] = job
            return Admission(AdmissionKind.ACCEPTED, job=job)

    def _release_locked(self, key: tuple[int, int]) -> None:
        job = self._active.pop(key, None)
        if job is not None:
            job.announced.set()

    async def active(self, guild_id: int, channel_id: int) -> ActiveJob | None:
        async with self._guard:
            return self._active.get((guild_id, channel_id))

    async def _remaining_locked(self, key: tuple[int, int], kind: CooldownKind) -> int:
        store = self._stores[kind]
        timer = kind, *key
        if store is None or timer in self._expired:
            return 0
        if timer in self._deadline:
            remaining = max(0, math.ceil(self._deadline[timer] - self.monotonic()))
            if remaining == 0:
                del self._deadline[timer]
                self._expired.add(timer)
            return remaining
        remaining = await asyncio.to_thread(store.remaining, *key, self.clock())
        if remaining > 0:
            self._deadline[timer] = self.monotonic() + remaining
        else:
            self._expired.add(timer)
        return remaining

    async def finish_success(
        self, guild_id: int, channel_id: int, at: datetime,
        kind: CooldownKind = CooldownKind.SUMMARY,
    ) -> None:
        key = guild_id, channel_id
        timer = kind, guild_id, channel_id
        store = self._stores[kind]
        async with self._guard:
            if store is not None:
                await asyncio.to_thread(store.record_success, guild_id, channel_id, at)
                expiry = at + timedelta(seconds=store.duration_seconds)
                remaining = min(store.duration_seconds, max(
                    0, math.ceil((expiry - self.clock()).total_seconds())
                ))
                self._expired.discard(timer)
                if remaining > 0:
                    self._deadline[timer] = self.monotonic() + remaining
                else:
                    self._deadline.pop(timer, None)
                    self._expired.add(timer)
            self._release_locked(key)

    async def finish(self, guild_id: int, channel_id: int) -> None:
        async with self._guard:
            self._release_locked((guild_id, channel_id))

    async def status(self, guild_id: int, channel_id: int) -> ChannelStatus:
        async with self._guard:
            if (guild_id, channel_id) in self._active:
                return ChannelStatus.SUMMARIZING
            if await self._remaining_locked((guild_id, channel_id), CooldownKind.SUMMARY) > 0:
                return ChannelStatus.COOLDOWN
            return ChannelStatus.IDLE
