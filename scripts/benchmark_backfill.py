"""Synthetic History delay plus disposable SQLite write contention; run on LXC."""

import asyncio
import json
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord

from yoyackbot.backfill import (
    BackfillPageScheduler,
    InitialBackfill,
    SQLiteBackfillStore,
    round_robin_backfills,
)
from yoyackbot.watch_store import SQLiteWatchStore


class Pages:
    async def fetch_page(self, channel: object, *, before: int, limit: int) -> list:
        await asyncio.sleep(0.02)
        messages = channel.synthetic_messages
        return [message for message in messages if message.id < before][:limit]


async def run(count: int, *, mixed_guilds: bool, concurrent: bool) -> dict:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "state.db"
        watches = SQLiteWatchStore(path)
        channels = [(1 if not mixed_guilds or index % 2 == 0 else 2, 100 + index)
                    for index in range(count)]
        for guild_id in {guild for guild, _ in channels}:
            watches.replace(guild_id, frozenset(
                channel_id for guild, channel_id in channels if guild == guild_id
            ))
        store = SQLiteBackfillStore(path)
        states = [store.get(guild, channel) for guild, channel in channels]
        assert all(state is not None for state in states)
        fake_channels = {}
        for state in states:
            guild = SimpleNamespace(id=state.guild_id)
            channel = SimpleNamespace(
                type=discord.ChannelType.text, id=state.channel_id, guild=guild,
            )
            started = datetime.fromtimestamp(state.started_us / 1_000_000, UTC)
            when = started - timedelta(minutes=1)
            channel.synthetic_messages = [SimpleNamespace(
                id=discord.utils.time_snowflake(when) + state.channel_id * 100 + index,
                guild=guild, channel=channel,
                author=SimpleNamespace(id=7, bot=False, display_name="합성 화자"),
                webhook_id=None, type=discord.MessageType.default,
                content="합성 기록", created_at=when, edited_at=None, attachments=(),
            ) for index in range(10, 0, -1)]
            fake_channels[state.channel_id] = channel
        worker = InitialBackfill(store, Pages())
        scheduler = BackfillPageScheduler()

        async def step(state) -> bool:
            channel = fake_channels[state.channel_id]
            if concurrent:
                return await scheduler.run(
                    state.guild_id, lambda: worker.step(channel, state)
                )
            return await worker.step(channel, state)

        started = time.monotonic()
        if concurrent:
            outcomes = await asyncio.gather(*(
                step(state) for state in round_robin_backfills(states)
            ))
        else:
            outcomes = [await step(state) for state in states]
        elapsed_ms = round((time.monotonic() - started) * 1000)
        assert all(outcomes)
        assert all(store.get(guild, channel).phase == "overlap" for guild, channel in channels)
        return {
            "channels": count,
            "guild_layout": "mixed" if mixed_guilds else "same",
            "mode": "bounded" if concurrent else "serial",
            "elapsed_ms": elapsed_ms,
            "pages_completed": len(outcomes),
        }


async def main() -> None:
    for mixed in (False, True):
        for count in (2, 4, 8):
            for concurrent in (False, True):
                print(json.dumps(await run(
                    count, mixed_guilds=mixed, concurrent=concurrent,
                ), sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
