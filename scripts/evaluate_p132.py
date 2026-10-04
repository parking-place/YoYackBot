"""T132-P2: real model, real command path — `request_timing` lines for synthetic commands (LXC only).

Builds a throwaway DB of synthetic messages, sends `!!요약좀` and `!!말하자면` through
`YoYackClient.on_message` with a stand-in channel (nothing reaches Discord), and prints the
timing lines as tables, then the raw lines. The service's settings are used except for the DB
and input paths, which point at a temporary directory.
"""

import asyncio
import io
import json
import logging
import sqlite3
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

sys.path.insert(0, str(Path(__file__).resolve().parent))

from show_timings import render, timings

from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import MessageRecord
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/summary_modes.json"
GUILD, CHANNEL = 1, 2


def allow(*_args) -> bool:
    return True


async def main_async(directory: Path, fixture_id: str) -> str:
    base = Settings.from_environment()
    settings = replace(base, database_path=directory / "db.sqlite", input_directory=directory / "inputs")
    settings.input_directory.mkdir(mode=0o700)
    now = datetime.now(UTC)
    watches = SQLiteWatchStore(settings.database_path)
    watches.replace(GUILD, frozenset({CHANNEL}))
    with sqlite3.connect(settings.database_path) as connection:
        stamp = int(now.timestamp() * 1_000_000)
        connection.execute("UPDATE backfill_state SET phase='ready', first_watch=0, started_us=?, "
                           "verified_us=?, finished_us=?", (stamp,) * 3)
    store = SQLiteMessageStore(settings.database_path, clock=lambda: datetime.now(UTC))
    fixture = next(f for f in json.loads(FIXTURES.read_text()) if f["id"] == fixture_id)
    people: dict[str, int] = {}
    total = len(fixture["messages"])
    for index, (key, name, body, *_flags) in enumerate(fixture["messages"], start=1):
        store.upsert(MessageRecord(
            discord.utils.time_snowflake(now - timedelta(minutes=total + 1 - index)), GUILD, CHANNEL,
            people.setdefault(key, len(people) + 1), name, body, now - timedelta(minutes=total + 1 - index),
        ), cached_at=now)

    for module in ("yoyackbot.workflow", "yoyackbot.publisher", "yoyackbot.watch_gate"):
        if hasattr(sys.modules.get(module), "valid_channel"):
            sys.modules[module].valid_channel = allow
    client = YoYackClient(watch_store=watches, message_store=store, settings=settings)
    client.cache_available = lambda: True
    posted: list[str] = []

    async def send(content, **_kwargs):
        posted.append(content)
        return SimpleNamespace(id=len(posted), channel=channel, created_at=datetime.now(UTC))

    channel = SimpleNamespace(id=CHANNEL, type=discord.ChannelType.text, name="합성 시험 채널",
                              send=send, history=Mock(), fetch_message=AsyncMock())
    guild = SimpleNamespace(id=GUILD, me=object(), get_channel=lambda _id: channel)
    channel.guild = guild
    client.get_channel = lambda _id: channel

    def command(content: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=discord.utils.time_snowflake(datetime.now(UTC)), guild=guild, channel=channel,
            content=content, webhook_id=None, author=SimpleNamespace(id=9, bot=False),
            type=discord.MessageType.default, reference=None, created_at=datetime.now(UTC),
        )

    try:
        await client.on_message(command("!!요약좀 3시간"))
        await client.on_message(command("!!말하자면"))
    finally:
        await client.close()
    return f"posted {len(posted)} messages (not shown)"


def main() -> None:
    fixture_id = sys.argv[1] if len(sys.argv) > 1 else "release_debate"
    lines = io.StringIO()
    handler = logging.StreamHandler(lines)
    logging.getLogger("yoyackbot.timing").addHandler(handler)
    logging.getLogger("yoyackbot.timing").setLevel(logging.INFO)
    with tempfile.TemporaryDirectory(dir="/var/tmp", prefix="yy-timing.") as directory:
        print(asyncio.run(main_async(Path(directory), fixture_id)))
    raw = lines.getvalue().splitlines()
    print("\n\n".join(render(item) for item in timings(raw)))
    print("\n" + "\n".join(raw))


if __name__ == "__main__":
    main()
