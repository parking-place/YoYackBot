"""Bounded cursor paging against a deterministic Discord History source."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.history import HistoryAdapter, HistoryError, HistoryFailure

START = datetime(2026, 9, 28, 12, tzinfo=UTC)
END = START + timedelta(minutes=3)


def channel(channel_id: int = 10) -> SimpleNamespace:
    return SimpleNamespace(id=channel_id, guild=SimpleNamespace(id=1), type=discord.ChannelType.text)


def message(
    when: datetime,
    suffix: int,
    *,
    bot: bool = False,
    webhook_id: int | None = None,
    kind: discord.MessageType = discord.MessageType.default,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=discord.utils.time_snowflake(when) + suffix,
        guild=SimpleNamespace(id=1),
        channel=channel(),
        author=SimpleNamespace(id=3, bot=bot, display_name="synthetic author"),
        webhook_id=webhook_id,
        type=kind,
        content="synthetic content",
        created_at=when,
        edited_at=None,
    )


class FakeSource:
    def __init__(self, messages, failures=None) -> None:
        self.messages = sorted(messages, key=lambda item: item.id, reverse=True)
        self.failures = list(failures or [])
        self.calls: list[tuple[int, int]] = []

    async def fetch_page(self, target, *, before: int, limit: int):
        self.calls.append((target.id, before))
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return [item for item in self.messages if item.id < before][:limit]


def test_page_boundaries_same_timestamp_fixed_end_and_filtered_authors() -> None:
    async def scenario() -> None:
        same = START + timedelta(minutes=1)
        wanted = [message(START, 1), message(same, 1), message(same, 2)]
        excluded = [
            message(same, 3, bot=True),
            message(same, 4, webhook_id=99),
            message(same, 5, kind=discord.MessageType.pins_add),
            message(same, 6),
            message(END, 1),
            message(END + timedelta(seconds=1), 1),
            message(START - timedelta(seconds=1), 1),
        ]
        source = FakeSource(wanted + excluded)
        adapter = HistoryAdapter(source, page_size=2, max_pages=20)
        result = await adapter.collect(
            channel(), guild_id=1, channel_id=10, start=START, end=END,
            trigger_message_id=excluded[3].id,
        )
        assert [item.message_id for item in result.messages] == [item.id for item in wanted]
        assert result.pages > 2
        assert all(target_id == 10 for target_id, _ in source.calls)
        assert len({item.message_id for item in result.messages}) == 3

    asyncio.run(scenario())


def test_channel_scope_and_page_limit_fail_closed() -> None:
    async def scenario() -> None:
        source = FakeSource([message(START + timedelta(minutes=1), index) for index in range(4)])
        adapter = HistoryAdapter(source, page_size=2, max_pages=1)
        with pytest.raises(HistoryError) as mismatch:
            await adapter.collect(channel(11), guild_id=1, channel_id=10, start=START, end=END)
        assert mismatch.value.kind is HistoryFailure.CHANNEL_MISMATCH
        assert source.calls == []
        with pytest.raises(HistoryError) as limit:
            await adapter.collect(channel(), guild_id=1, channel_id=10, start=START, end=END)
        assert limit.value.kind is HistoryFailure.PAGE_LIMIT
        assert len(source.calls) == 1

    asyncio.run(scenario())


def test_transient_retry_and_middle_page_failure_never_signal_completion() -> None:
    async def scenario() -> None:
        messages = [message(START + timedelta(minutes=1), index) for index in range(4)]
        retry_source = FakeSource(messages, failures=[OSError("synthetic network gap")])
        result = await HistoryAdapter(retry_source, page_size=2, retries=1).collect(
            channel(), guild_id=1, channel_id=10, start=START, end=END
        )
        assert len(result.messages) == 4
        assert len(retry_source.calls) >= 3

        class FailSecondPage(FakeSource):
            async def fetch_page(self, target, *, before: int, limit: int):
                if len(self.calls) >= 1:
                    self.calls.append((target.id, before))
                    raise OSError("synthetic second-page failure")
                return await super().fetch_page(target, before=before, limit=limit)

        failed = FailSecondPage(messages)
        with pytest.raises(HistoryError) as error:
            await HistoryAdapter(failed, page_size=2, retries=1).collect(
                channel(), guild_id=1, channel_id=10, start=START, end=END
            )
        assert error.value.kind is HistoryFailure.NETWORK
        assert len(failed.calls) == 3

    asyncio.run(scenario())


def test_forbidden_is_not_retried_and_total_timeout_is_bounded() -> None:
    async def scenario() -> None:
        forbidden = discord.Forbidden.__new__(discord.Forbidden)
        Exception.__init__(forbidden, "synthetic permission denial")
        forbidden.status = 403
        source = FakeSource([], failures=[forbidden])
        with pytest.raises(HistoryError) as denied:
            await HistoryAdapter(source, retries=2).collect(
                channel(), guild_id=1, channel_id=10, start=START, end=END
            )
        assert denied.value.kind is HistoryFailure.PERMISSION
        assert len(source.calls) == 1

        class SlowSource(FakeSource):
            async def fetch_page(self, target, *, before: int, limit: int):
                await asyncio.sleep(0.1)
                return []

        with pytest.raises(HistoryError) as timed_out:
            await HistoryAdapter(SlowSource([]), timeout_seconds=0.01).collect(
                channel(), guild_id=1, channel_id=10, start=START, end=END
            )
        assert timed_out.value.kind is HistoryFailure.TIMEOUT

    asyncio.run(scenario())


def test_rate_limit_and_missing_channel_are_classified() -> None:
    async def scenario() -> None:
        for error_type, status, expected, calls in (
            (discord.HTTPException, 429, HistoryFailure.RATE_LIMIT, 2),
            (discord.NotFound, 404, HistoryFailure.CHANNEL_GONE, 1),
        ):
            error = error_type.__new__(error_type)
            Exception.__init__(error, "synthetic HTTP error")
            error.status = status
            source = FakeSource([], failures=[error] * 2)
            with pytest.raises(HistoryError) as failed:
                await HistoryAdapter(source, retries=1).collect(
                    channel(), guild_id=1, channel_id=10, start=START, end=END
                )
            assert failed.value.kind is expected
            assert len(source.calls) == calls

    asyncio.run(scenario())


def test_out_of_order_or_cross_channel_page_fails_closed() -> None:
    async def scenario() -> None:
        first = message(START + timedelta(minutes=1), 2)
        second = message(START + timedelta(minutes=1), 1)

        class MalformedSource(FakeSource):
            def __init__(self, response) -> None:
                super().__init__([])
                self.response = response

            async def fetch_page(self, target, *, before: int, limit: int):
                return self.response

        wrong_channel = message(START + timedelta(minutes=1), 3)
        wrong_channel.channel = channel(11)
        for response in ([second, first], [wrong_channel], [first, first]):
            with pytest.raises(HistoryError) as failed:
                await HistoryAdapter(MalformedSource(response)).collect(
                    channel(), guild_id=1, channel_id=10, start=START, end=END
                )
            assert failed.value.kind is HistoryFailure.INVALID_PAGE

    asyncio.run(scenario())


def test_message_count_and_utf8_byte_budgets_stop_paging() -> None:
    async def scenario() -> None:
        messages = [message(START + timedelta(minutes=1), index) for index in range(3)]
        with pytest.raises(HistoryError) as count_error:
            await HistoryAdapter(FakeSource(messages), max_records=2).collect(
                channel(), guild_id=1, channel_id=10, start=START, end=END
            )
        assert count_error.value.kind is HistoryFailure.SIZE_LIMIT
        with pytest.raises(HistoryError) as byte_error:
            await HistoryAdapter(FakeSource(messages), max_content_bytes=5).collect(
                channel(), guild_id=1, channel_id=10, start=START, end=END
            )
        assert byte_error.value.kind is HistoryFailure.SIZE_LIMIT

    asyncio.run(scenario())


def test_count_limited_history_stops_after_latest_three_without_claiming_coverage() -> None:
    async def scenario() -> None:
        messages = [message(START + timedelta(minutes=1), index) for index in range(20)]
        source = FakeSource(messages)
        result = await HistoryAdapter(source, page_size=5).collect(
            channel(), guild_id=1, channel_id=10, start=START, end=END,
            limit_messages=3,
        )
        assert [item.message_id for item in result.messages] == [item.id for item in messages[-3:]]
        assert result.pages == 1 and not result.exhausted
        assert len(source.calls) == 1

    asyncio.run(scenario())
