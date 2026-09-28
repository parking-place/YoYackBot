"""Atomic per-Guild/channel admission for summary jobs."""

import asyncio
from enum import Enum


class ChannelStatus(Enum):
    IDLE = "idle"
    SUMMARIZING = "summarizing"
    COOLDOWN = "cooldown"


class ChannelStates:
    def __init__(self) -> None:
        self._active: set[tuple[int, int]] = set()
        self._guard = asyncio.Lock()

    async def begin(self, guild_id: int, channel_id: int) -> bool:
        key = guild_id, channel_id
        async with self._guard:
            if key in self._active:
                return False
            self._active.add(key)
            return True

    async def finish(self, guild_id: int, channel_id: int) -> None:
        async with self._guard:
            self._active.discard((guild_id, channel_id))

    async def status(self, guild_id: int, channel_id: int) -> ChannelStatus:
        async with self._guard:
            if (guild_id, channel_id) in self._active:
                return ChannelStatus.SUMMARIZING
            return ChannelStatus.IDLE
