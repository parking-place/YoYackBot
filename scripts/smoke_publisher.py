"""Post and verify a synthetic multi-part summary in the configured dev channel."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import discord

from yoyackbot.config import Settings
from yoyackbot.discord import required_intents
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryRequest, SummaryResult
from yoyackbot.publisher import DiscordSummaryPublisher
from yoyackbot.watch_store import SQLiteWatchStore


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
            now = datetime.now(UTC)
            request = SummaryRequest(
                guild_id, channel_id, 1,
                RangeRequest(RequestKind.TIME, now, start=now - timedelta(minutes=10)),
            )
            selected = [MessageRecord(
                1, guild_id, channel_id, 1, "합성 사용자", "시험용 대화",
                now - timedelta(minutes=5),
            )]
            body = "합성 게시 시험이며 실제 대화 내용은 포함하지 않았소.\n" * 100
            body += "멘션 확인: @everyone <@123456>"
            publisher = DiscordSummaryPublisher(
                client, SQLiteWatchStore(settings.database_path), settings
            )
            receipt = await publisher.publish(
                request, SummaryResult(body, "synthetic", 1), selected
            )
            channel = client.get_channel(channel_id)
            assert isinstance(channel, discord.TextChannel)
            checked = [await channel.fetch_message(message_id) for message_id in receipt.message_ids]
            assert len(checked) >= 2
            assert all(message.channel.id == channel_id for message in checked)
            assert all(not message.mention_everyone and not message.mentions
                       and not message.role_mentions for message in checked)
            assert "부터 지금까지의 요약이오" in checked[0].content
            assert all("부터 지금까지의 요약이오" not in message.content
                       for message in checked[1:])
            assert receipt.last_success_at == checked[-1].created_at
            print("live_publisher_pass", "parts", len(checked), "mentions", 0)
        finally:
            await client.close()
            await asyncio.gather(running, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
