"""Fail-closed publication, permission rechecks and ambiguous-send handling."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryRequest, SummaryResult
from yoyackbot.publisher import DiscordSummaryPublisher, PartialPublicationError, PublicationFailure
from yoyackbot.summary_format import format_summary

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


class FakeChannel:
    type = discord.ChannelType.text

    def __init__(self, *, guild_id: int = 1, channel_id: int = 2) -> None:
        self.id = channel_id
        self.guild = SimpleNamespace(id=guild_id)
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.fail_at: int | None = None
        self.on_send: object = None

    async def send(self, content: str, **kwargs: object) -> object:
        self.sent.append((content, kwargs))
        if callable(self.on_send):
            self.on_send(len(self.sent))
        if self.fail_at == len(self.sent):
            raise TimeoutError("response lost")
        return SimpleNamespace(
            id=100 + len(self.sent), channel=self, created_at=NOW + timedelta(seconds=len(self.sent))
        )


def fixture(length: int = 400) -> tuple[
    DiscordSummaryPublisher, SummaryRequest, SummaryResult, list[MessageRecord], FakeChannel,
    MemoryWatchStore,
]:
    config = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_DISCORD_MESSAGE_LIMIT": "120",
    })
    watch = MemoryWatchStore()
    watch.replace(1, frozenset({2}))
    channel = FakeChannel()
    client = SimpleNamespace(get_channel=lambda _id: channel)
    publisher = DiscordSummaryPublisher(client, watch, config, clock=lambda: NOW)  # type: ignore[arg-type]
    time_range = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
    request = SummaryRequest(1, 2, 3, time_range)
    selected = [MessageRecord(4, 1, 2, 3, "가람", "합성", NOW - timedelta(minutes=2))]
    result = SummaryResult("가람이 기록하였소. " * length, "gpt-6-luna", 1)
    return publisher, request, result, selected, channel, watch


def test_success_sends_only_to_requested_channel_and_returns_last_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda _guild, _id: True)
    publisher, request, result, selected, channel, _watch = fixture(10)
    receipt = asyncio.run(publisher.publish(request, result, selected))
    assert len(receipt.message_ids) == len(channel.sent)
    assert receipt.last_success_at == NOW + timedelta(seconds=len(channel.sent))
    assert all(kwargs["allowed_mentions"].everyone is False for _, kwargs in channel.sent)
    assert all(kwargs["suppress_embeds"] is True for _, kwargs in channel.sent)
    assert "부터 지금까지의 요약이오" in channel.sent[0][0]
    assert all("부터 지금까지의 요약이오" not in item[0] for item in channel.sent[1:])


@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_ambiguous_send_never_retries(
    position: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda _guild, _id: True)
    publisher, request, result, selected, channel, _watch = fixture()
    count = len(format_summary(request.requested_range, selected, result,
                               publisher.settings.timezone, limit=120))
    fail_at = {"first": 1, "middle": count // 2, "last": count}[position]
    channel.fail_at = fail_at
    with pytest.raises(PartialPublicationError) as raised:
        asyncio.run(publisher.publish(request, result, selected))
    assert raised.value.reason is PublicationFailure.UNCERTAIN
    assert raised.value.failed_index == fail_at
    assert len(raised.value.sent_ids) == fail_at - 1
    assert len(channel.sent) == fail_at


def test_watch_removed_mid_publish_stops_before_next_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda _guild, _id: True)
    publisher, request, result, selected, channel, watch = fixture()
    channel.on_send = lambda index: watch.replace(1, frozenset()) if index == 1 else None
    with pytest.raises(PartialPublicationError) as raised:
        asyncio.run(publisher.publish(request, result, selected))
    assert raised.value.reason is PublicationFailure.UNWATCHED
    assert len(raised.value.sent_ids) == len(channel.sent) == 1


def test_wrong_guild_and_permission_loss_fail_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher, request, result, selected, channel, _watch = fixture()
    channel.guild.id = 99
    with pytest.raises(PartialPublicationError) as raised:
        asyncio.run(publisher.publish(request, result, selected))
    assert raised.value.reason is PublicationFailure.CHANNEL_UNAVAILABLE
    assert channel.sent == []
    channel.guild.id = 1
    monkeypatch.setattr("yoyackbot.publisher.valid_channel", lambda _guild, _id: False)
    with pytest.raises(PartialPublicationError) as raised:
        asyncio.run(publisher.publish(request, result, selected))
    assert raised.value.reason is PublicationFailure.PERMISSION
    assert channel.sent == []


def test_permission_loss_between_chunks_preserves_sent_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = 0

    def permission(_guild: object, _id: int) -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    monkeypatch.setattr("yoyackbot.publisher.valid_channel", permission)
    publisher, request, result, selected, channel, _watch = fixture()
    with pytest.raises(PartialPublicationError) as raised:
        asyncio.run(publisher.publish(request, result, selected))
    assert raised.value.reason is PublicationFailure.PERMISSION
    assert raised.value.failed_index == 2
    assert raised.value.sent_ids == (101,)
    assert raised.value.last_success_at == NOW + timedelta(seconds=1)
    assert len(channel.sent) == 1
