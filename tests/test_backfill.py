"""First-watch import crosses page, restart, and live-ingress boundaries."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.backfill import BackfillError, InitialBackfill, SQLiteBackfillStore
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
        started = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=state.started_us)
        channel = fake_channel()
        old = [
            fake_message(channel, started - timedelta(minutes=index), index=index)
            for index in range(1, 20_101)
        ]
        live = fake_message(channel, started + timedelta(seconds=1), index=20_102)
        missed = fake_message(channel, started + timedelta(seconds=2), index=20_103)
        at_start = fake_message(channel, started, index=20_108)
        at_finish = fake_message(channel, started + timedelta(seconds=10), index=20_109)
        at_cutoff = fake_message(channel, started - timedelta(days=30), index=20_110)
        older = fake_message(channel, started - timedelta(days=31), index=20_104)
        command = fake_message(channel, started - timedelta(seconds=3), index=20_105)
        command.content = "!!요약좀 5분"
        bot = fake_message(channel, started - timedelta(seconds=4), index=20_106)
        bot.author.bot = True
        webhook = fake_message(channel, started - timedelta(seconds=5), index=20_107)
        webhook.webhook_id = 9
        source = FakePages([
            *old, live, missed, at_start, at_finish, at_cutoff,
            older, command, bot, webhook,
        ])
        messages = SQLiteMessageStore(path)
        watches_version = watches.version(1)
        assert messages.upsert_if_watched(
            MessageRecord(live.id, 1, 99, 7, "합성 화자", live.content, live.created_at),
            expected_version=watches_version, cached_at=started,
        )
        assert messages.upsert_if_watched(
            MessageRecord(
                at_finish.id, 1, 99, 7, "합성 화자", at_finish.content, at_finish.created_at
            ),
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
        assert len(stored) == 20_105
        assert len({item.message_id for item in stored}) == len(stored)
        assert {live.id, missed.id, at_start.id, at_finish.id, at_cutoff.id} <= {
            item.message_id for item in stored
        }

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


def test_preexisting_watch_is_migrated_without_first_watch_announcement(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM backfill_state")
    backfills = SQLiteBackfillStore(path)
    assert backfills.ensure_existing() == 1
    migrated = backfills.get(1, 99)
    assert migrated is not None and not migrated.first_watch
    assert backfills.ensure_existing() == 0


def test_history_page_cannot_undo_newer_live_edit_or_delete(tmp_path) -> None:
    path = tmp_path / "messages.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    backfills = SQLiteBackfillStore(path)
    state = backfills.get(1, 99)
    assert state is not None
    now = datetime.now(UTC)
    original = MessageRecord(123, 1, 99, 7, "합성 화자", "예전 본문", now - timedelta(hours=1))
    messages = SQLiteMessageStore(path)
    messages.upsert(original, cached_at=now)
    assert messages.update_content(
        1, 99, 123, "새 본문", edited_at=now, cached_at=now
    )
    assert backfills.save_page(
        state, (original,), next_cursor=state.cursor - 1,
        next_phase="history", finished_at=None, cached_at=now,
    )
    assert messages.recent(1, 99, now - timedelta(days=1), now)[0].content == "새 본문"
    assert messages.delete_many(1, 99, {123}) == 1
    current = backfills.get(1, 99)
    assert current is not None
    assert backfills.save_page(
        current, (original,), next_cursor=current.cursor - 1,
        next_phase="history", finished_at=None, cached_at=now,
    )
    assert messages.recent(1, 99, now - timedelta(days=1), now) == []


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
        started = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=state.started_us)
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

        assert backfills.schedule_ready_recheck(
            start=started + timedelta(seconds=2), end=started + timedelta(seconds=10)
        ) == 1
        with pytest.raises(BackfillNotReady):
            await collector.collect(channel, guild_id=1, channel_id=99, request=request)
        gap_message = fake_message(channel, started + timedelta(seconds=3), index=202)
        empty.messages = [gap_message]
        gap = backfills.get(1, 99)
        assert gap is not None and gap.phase == "overlap"
        assert await worker.step(channel, gap)
        repaired = await collector.collect(channel, guild_id=1, channel_id=99, request=request)
        assert {item.message_id for item in repaired.messages} == {101, gap_message.id}

    asyncio.run(scenario())


def test_network_failure_keeps_cursor_for_a_later_retry(tmp_path) -> None:
    async def scenario() -> None:
        path = tmp_path / "messages.db"
        watches = SQLiteWatchStore(path)
        watches.replace(1, frozenset({99}))
        backfills = SQLiteBackfillStore(path)
        state = backfills.get(1, 99)
        assert state is not None

        class FlakyPages:
            calls = 0

            async def fetch_page(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("synthetic network loss")
                return []

        worker = InitialBackfill(backfills, FlakyPages())
        with pytest.raises(BackfillError):
            await worker.step(fake_channel(), state)
        unchanged = backfills.get(1, 99)
        assert unchanged is not None and unchanged.cursor == state.cursor
        assert unchanged.phase == "history"
        assert await worker.step(fake_channel(), unchanged)
        assert backfills.get(1, 99).phase == "overlap"  # type: ignore[union-attr]

    asyncio.run(scenario())
