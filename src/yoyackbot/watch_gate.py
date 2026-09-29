"""Fail-closed watched-channel boundary for ingestion and summary requests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from yoyackbot.channel_config import WatchStore

LOGGER = logging.getLogger(__name__)
UNWATCHED_NOTICE = "이 채널은 아직 살피고 있지 않소. `/채널 설정`으로 먼저 정하시오."
UNAVAILABLE_NOTICE = "채널 설정을 확인하지 못했소. 잠시 후 다시 시도하시오."
T = TypeVar("T")


class GateResult(Enum):
    HELP = "help"
    UNWATCHED = "unwatched"
    UNAVAILABLE = "unavailable"
    ACCEPTED = "accepted"


@dataclass(frozen=True)
class ChannelLease:
    store: WatchStore
    guild_id: int
    channel_id: int
    version: int

    def valid(self) -> bool:
        try:
            version, channels = self.store.snapshot(self.guild_id)
            return version == self.version and self.channel_id in channels
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_lease_check_failed")
            return False


class WatchGate:
    def __init__(self, store: WatchStore) -> None:
        self.store = store

    def lease(self, guild_id: int, channel_id: int) -> tuple[GateResult, ChannelLease | None]:
        try:
            version, channels = self.store.snapshot(guild_id)
            watched = channel_id in channels
        except Exception:  # noqa: BLE001
            LOGGER.warning("watched_channel_lookup_failed")
            return GateResult.UNAVAILABLE, None
        if not watched:
            return GateResult.UNWATCHED, None
        return GateResult.ACCEPTED, ChannelLease(self.store, guild_id, channel_id, version)

    async def ingest(
        self,
        guild_id: int,
        channel_id: int,
        message: T,
        save: Callable[[T, ChannelLease], Awaitable[None]],
    ) -> GateResult:
        result, lease = await asyncio.to_thread(self.lease, guild_id, channel_id)
        if lease is None:
            return result
        if not await asyncio.to_thread(lease.valid):
            return GateResult.UNWATCHED
        await save(message, lease)
        return GateResult.ACCEPTED

    async def request(
        self,
        guild_id: int,
        channel_id: int,
        *,
        is_help: bool,
        help_reply: Callable[[], Awaitable[None]],
        unwatched_reply: Callable[[str], Awaitable[None]],
        unavailable_reply: Callable[[str], Awaitable[None]],
        summarize: Callable[[ChannelLease], Awaitable[None]],
    ) -> GateResult:
        if is_help:
            await help_reply()
            return GateResult.HELP
        result, lease = await asyncio.to_thread(self.lease, guild_id, channel_id)
        if result is GateResult.UNAVAILABLE:
            await unavailable_reply(UNAVAILABLE_NOTICE)
            return result
        if lease is None:
            await unwatched_reply(UNWATCHED_NOTICE)
            return GateResult.UNWATCHED
        if not await asyncio.to_thread(lease.valid):
            await unwatched_reply(UNWATCHED_NOTICE)
            return GateResult.UNWATCHED
        await summarize(lease)
        return GateResult.ACCEPTED
