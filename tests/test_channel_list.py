"""`!!요약좀 채널` lists this Guild's watched channels the requester can see (T102b-P1)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.channel_list import visible_watched_channels
from yoyackbot.discord import YoYackClient
from yoyackbot.parser import RouteKind, route_trigger
from yoyackbot.watch_gate import UNAVAILABLE_NOTICE, UNWATCHED_NOTICE


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        ("!!요약좀 채널", RouteKind.CHANNELS),
        ("  !!요약좀   채널  ", RouteKind.CHANNELS),
        ("!!요약좀 채널 도움", RouteKind.HELP),
        ("!!요약좀 채널 부탁하오", RouteKind.SUMMARY),
        ("!!요약좀 3시간 채널", RouteKind.SUMMARY),
        ("!!요약좀 채널좀", RouteKind.SUMMARY),
        ("!!요약좀 사용량", RouteKind.USAGE),
        ("!!요약좀 상태", RouteKind.STATUS),
    ],
)
def test_channel_route_is_one_exact_word(content: str, kind: RouteKind) -> None:
    assert route_trigger(content).kind is kind


class Requester:
    def __init__(self, hidden: set[int] = frozenset()) -> None:
        self.hidden = hidden


def text_channel(channel_id: int, name: str, position: int, category: int | None = None,
                 kind: discord.ChannelType = discord.ChannelType.text) -> SimpleNamespace:
    channel = SimpleNamespace(
        id=channel_id, name=name, position=position, type=kind,
        category=None if category is None else SimpleNamespace(position=category),
        send=AsyncMock(),
    )
    channel.permissions_for = lambda member: SimpleNamespace(
        view_channel=channel_id not in member.hidden
    )
    return channel


def guild(guild_id: int, channels: list[SimpleNamespace]) -> SimpleNamespace:
    by_id = {channel.id: channel for channel in channels}
    return SimpleNamespace(id=guild_id, get_channel=by_id.get)


CHANNELS = [
    text_channel(10, "기획", 2, category=1),
    text_channel(11, "잡담", 0),
    text_channel(12, "개발", 1, category=1),
    text_channel(13, "비밀", 0, category=1),
    text_channel(14, "음성", 0, kind=discord.ChannelType.voice),
    text_channel(15, "같은위치", 1, category=1),
]


def test_selection_orders_and_filters() -> None:
    names = [
        channel.name for channel in visible_watched_channels(
            guild(1, CHANNELS), {10, 11, 12, 13, 14, 15, 99}, Requester(hidden={13}),
        )
    ]
    assert names == ["잡담", "개발", "같은위치", "기획"]


def test_permission_errors_skip_the_channel() -> None:
    broken = text_channel(20, "고장", 0)
    broken.permissions_for = lambda _member: (_ for _ in ()).throw(AttributeError)
    assert visible_watched_channels(guild(1, [broken]), {20}, object()) == []


def event(content: str, channel: SimpleNamespace, guild_obj: SimpleNamespace,
          requester: Requester) -> SimpleNamespace:
    return SimpleNamespace(
        id=500, guild=guild_obj, channel=channel, author=requester, webhook_id=None,
        type=discord.MessageType.default, content=content,
    )


class NoWorkflow:
    async def run(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("channel list must not start a summary job")

    async def shutdown(self) -> None:
        return None


def run_command(store: object, where: SimpleNamespace, guild_obj: SimpleNamespace,
                requester: Requester) -> list[str]:
    async def scenario() -> list[str]:
        client = YoYackClient(watch_store=store, summary_workflow=NoWorkflow())  # type: ignore[arg-type]
        try:
            await client.on_message(event("!!요약좀 채널", where, guild_obj, requester))
        finally:
            await client.close()
        assert all(call.kwargs["allowed_mentions"].to_dict()["parse"] == []
                   for call in where.send.await_args_list)
        return [call.args[0] for call in where.send.await_args_list]

    return asyncio.run(scenario())


def test_watched_channel_gets_only_this_guilds_visible_list(caplog) -> None:
    caplog.set_level(logging.INFO)
    store = MemoryWatchStore()
    store.replace(1, frozenset({10, 11, 12, 13}))
    store.replace(2, frozenset({30}))
    here = text_channel(11, "잡담", 0)
    channels = [channel for channel in CHANNELS if channel.id != 11] + [here]
    texts = run_command(store, here, guild(1, channels), Requester(hidden={13}))
    assert texts == ["지금 본인이 보고 있는 채널을 알려주겠소\n - 잡담\n - 개발\n - 기획\n이상이오."]
    assert "channel_list_request count=3" in caplog.text
    assert "잡담" not in caplog.text and "비밀" not in caplog.text


def test_unwatched_channel_gets_only_the_unwatched_notice() -> None:
    store = MemoryWatchStore()
    store.replace(1, frozenset({10, 12}))
    here = text_channel(11, "잡담", 0)
    texts = run_command(store, here, guild(1, CHANNELS[:1] + [here]), Requester())
    assert texts == [UNWATCHED_NOTICE]


def test_unreadable_settings_invent_no_list() -> None:
    class Broken(MemoryWatchStore):
        def snapshot(self, guild_id: int):  # type: ignore[override]
            raise RuntimeError("database locked")

    here = text_channel(11, "잡담", 0)
    assert run_command(Broken(), here, guild(1, [here]), Requester()) == [UNAVAILABLE_NOTICE]


def test_settings_failure_after_gate_invents_no_list() -> None:
    class FlakyStore(MemoryWatchStore):
        calls = 0

        def snapshot(self, guild_id: int):  # type: ignore[override]
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("database locked")
            return super().snapshot(guild_id)

    store = FlakyStore()
    store.replace(1, frozenset({11}))
    here = text_channel(11, "잡담", 0)
    assert run_command(store, here, guild(1, [here]), Requester()) == [UNAVAILABLE_NOTICE]


def test_reply_while_a_summary_is_running() -> None:
    async def scenario() -> None:
        from yoyackbot.parser import OptionKind
        from yoyackbot.scope import RangeScope
        from yoyackbot.state import ChannelStates

        states = ChannelStates()
        await states.admit(1, 11, scope=RangeScope(OptionKind.DAYS, 10))
        store = MemoryWatchStore()
        store.replace(1, frozenset({11}))
        here = text_channel(11, "잡담", 0)
        workflow = SimpleNamespace(states=states, run=AsyncMock(), shutdown=AsyncMock())
        client = YoYackClient(watch_store=store, summary_workflow=workflow)  # type: ignore[arg-type]
        try:
            await client.on_message(event("!!요약좀 채널", here, guild(1, [here]), Requester()))
        finally:
            await client.close()
        workflow.run.assert_not_awaited()
        assert here.send.await_args.args[0].endswith(" - 잡담\n이상이오.")
        assert (await states.active(1, 11)) is not None

    asyncio.run(scenario())
