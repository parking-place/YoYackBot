"""Manual dev-only path: verified human messages -> Codex -> same-channel output."""

import asyncio
import os
from datetime import UTC, datetime

import discord

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.collection import CollectionCoordinator
from yoyackbot.config import Settings
from yoyackbot.count_collection import CountCollector
from yoyackbot.discord import required_intents
from yoyackbot.domain import RangeRequest, RequestKind, SummaryRequest
from yoyackbot.history import HistoryAdapter
from yoyackbot.long_range import LongRangeCollector
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.publisher import DiscordSummaryPublisher
from yoyackbot.range_collection import TimeRangeCollector
from yoyackbot.watch_store import SQLiteWatchStore

EXPECTED = (
    "통합시험: 가람은 금요일 배포를 제안했소",
    "통합시험: 나래는 일정 검토 후 결정하자고 했소",
    "통합시험: 배포 날짜는 아직 미정이오",
)


async def main() -> None:
    settings = Settings.from_environment()
    guild_id = settings.dev_guild_id
    channel_id = int(os.environ["YOYACK_DEV_CHANNEL_ID"])
    if guild_id is None:
        raise ValueError("Development guild is required")
    client = discord.Client(
        intents=required_intents(), member_cache_flags=discord.MemberCacheFlags.none()
    )
    async with client:
        running = asyncio.create_task(client.start(settings.discord_bot_token))
        try:
            await asyncio.wait_for(client.wait_until_ready(), timeout=30)
            channel = client.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild_id:
                raise ValueError("Development text channel unavailable")
            watches = SQLiteWatchStore(settings.database_path)
            store = SQLiteMessageStore(settings.database_path)
            history = HistoryAdapter(max_pages=settings.max_history_pages)
            recent = TimeRangeCollector(store, watches, history)
            collector = CollectionCoordinator(
                watches,
                LongRangeCollector(recent, history, max_content_bytes=settings.max_input_bytes),
                CountCollector(
                    recent, history, max_count=settings.max_messages,
                    max_content_bytes=settings.max_input_bytes,
                    max_pages=settings.max_history_pages,
                ),
                history, max_count=settings.max_messages,
                max_content_bytes=settings.max_input_bytes,
                max_pages=settings.max_history_pages,
            )
            requested = RangeRequest(RequestKind.COUNT, datetime.now(UTC), count=3)
            collected = await collector.collect(
                channel, guild_id=guild_id, channel_id=channel_id, request=requested
            )
            if tuple(item.content.strip() for item in collected.messages) != EXPECTED:
                raise ValueError("Latest three human messages are not the approved synthetic set")
            engine = CodexSummaryEngine.from_settings(settings)
            summary = await engine.summarize(
                collected.messages, channel_name=channel.name, range_label="최근 3개 메시지"
            )
            receipt = await DiscordSummaryPublisher(client, watches, settings).publish(
                SummaryRequest(guild_id, channel_id, 1, requested), summary,
                collected.messages,
            )
            posted = [await channel.fetch_message(message_id) for message_id in receipt.message_ids]
            assert all(item.channel.id == channel_id for item in posted)
            assert all(not item.mention_everyone and not item.mentions and not item.role_mentions
                       for item in posted)
            assert all(len(item.content) <= settings.discord_message_limit for item in posted)
            assert "부터 지금까지의 요약이오" in posted[0].content
            assert all("부터 지금까지의 요약이오" not in item.content for item in posted[1:])
            assert receipt.last_success_at == posted[-1].created_at
            assert not any(settings.input_directory.glob("request-*"))
            print("pipeline_pass", "selected", len(collected.messages),
                  "parts", len(posted), "history_pages", collected.pages,
                  "fallback", collected.fallback_used)
            print("synthetic_summary", summary.text)
        finally:
            await client.close()
            await asyncio.gather(running, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
