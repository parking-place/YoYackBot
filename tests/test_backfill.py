"""First-watch import crosses page, restart, and live-ingress boundaries."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.backfill import InitialBackfill, SQLiteBackfillStore
from yoyackbot.cache_collector import BackfillNotReady, CacheOnlyCollector
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore


def fake_channel() -> SimpleNamespace:
    return SimpleNamespace(
        type=discord.ChannelType.text, id=99, guild=SimpleNamespace(id=1),
    )


def fake_message(channel: SimpleNamespace, when: datetime, *, index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=discord.utils.time_snowflake(when) + index,
        guild=channel.guild, channel=channel,
        author=SimpleNamespace(id=7, bot=False, display_name="합성 화자"),
        webhook_id=None, type=discord.MessageType.default,
        content=f"합성 {index}", created_at=when, edited_at=None,
        attachments=(),
    )


class FakePages:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.messages = sorted(messages, key=lambda item: item.id, reverse=True)
        self.calls = 0

    async def fetch_page(
        self, _channel: SimpleNamespace, *, before: int, limit: int,
    ) -> list[SimpleNamespace]:
        self.calls += 1
        return [item for item in self.messages if item.id < before][:limit]


def test_full_history_over_200_pages_rechecks_live_overlap_after_restart(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({99}))
        backfills = SQLiteBackfillStore(path)
        state = backfills.get(1, 99)
        assert state is not None and state.first_watch
        started = datetime.fromtimestamp(state.started_us / 1_000_000, UTC)
        channel = fake_channel()
        old = [
            fake_message(channel, started - timedelta(minutes=index), index=index)
            for index in range(1, 20_101)
        ]
        live = fake_message(channel, started + timedelta(seconds=1), index=20_102)
        missed = fake_message(channel, started + timedelta(seconds=2), index=20_103)
        source = FakePages([*old, live, missed])
        messages = SQLiteMessageStore(path)
        watches_version = watches.version(1)
        assert messages.upsert_if_watched(
            MessageRecord(live.id, 1, 99, 7, "합성 화자", live.content, live.created_at),
            expected_version=watches_version, cached_at=started,
        )
        worker = InitialBackfill(backfills, source, clock=lambda: started + timedelta(seconds=10))
        for turn in range(220):
            current = backfills.get(1, 99)
            assert current is not None
            if current.ready:
                break
            if turn == 110:
                backfills = SQLiteBackfillStore(path)
                worker = InitialBackfill(
                    backfills, source, clock=lambda: started + timedelta(seconds=10)
                )
            assert await worker.step(channel, current)
        else:
            raise AssertionError("Backfill did not finish")
        ready = backfills.get(1, 99)
        assert ready is not None and ready.ready and ready.verified_us is not None
        assert source.calls >= 202
        stored = messages.recent(
            1, 99, started - timedelta(days=30), started + timedelta(seconds=11)
        )
        assert len(stored) == 20_102
        assert len({item.message_id for item in stored}) == len(stored)
        assert {live.id, missed.id} <= {item.message_id for item in stored}

    asyncio.run(scenario())


def test_unwatch_invalidates_inflight_page_and_rewatch_starts_new_generation(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    backfills = SQLiteBackfillStore(path)
    old = backfills.get(1, 99)
    assert old is not None
    watches.replace(1, frozenset())
    assert not backfills.save_page(
        old, (), next_cursor=old.before_id - 1, next_phase="history",
        finished_at=None, cached_at=datetime.now(UTC),
    )
    watches.replace(1, frozenset({99}))
    new = backfills.get(1, 99)
    assert new is not None and new.token != old.token and not new.ready


def test_normal_summary_uses_ready_cache_only(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({99}))
        backfills = SQLiteBackfillStore(path)
        messages = SQLiteMessageStore(path)
        channel = fake_channel()
        collector = CacheOnlyCollector(watches, messages, backfills)
        state = backfills.get(1, 99)
        assert state is not None
        started = datetime.fromtimestamp(state.started_us / 1_000_000, UTC)
        request = RangeRequest(
            RequestKind.TIME, started + timedelta(seconds=10),
            start=started - timedelta(hours=1),
        )
        with pytest.raises(BackfillNotReady):
            await collector.collect(channel, guild_id=1, channel_id=99, request=request)
        empty = FakePages([])
        worker = InitialBackfill(backfills, empty, clock=lambda: started + timedelta(seconds=1))
        assert await worker.step(channel, state)
        overlap = backfills.get(1, 99)
        assert overlap is not None and overlap.phase == "overlap"
        assert await worker.step(channel, overlap)
        assert backfills.get(1, 99).ready  # type: ignore[union-attr]
        messages.upsert(
            MessageRecord(101, 1, 99, 7, "합성 화자", "캐시 대화", started),
            cached_at=started,
        )
        result = await collector.collect(channel, guild_id=1, channel_id=99, request=request)
        assert [item.message_id for item in result.messages] == [101]
        assert result.pages == 0 and result.history_count == 0 and result.cache_count == 1
        assert empty.calls == 2

    asyncio.run(scenario())
