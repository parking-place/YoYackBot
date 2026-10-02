"""`!!요약좀 채널` lists this Guild's watched channels the requester can see (T102b-P1)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from yoyackbot.channel_config import MemoryWatchStore
from yoyackbot.channel_list import (
    DM_DELIVERED_NOTICE,
    DM_FAILED_NOTICE,
    deliver_channel_list,
    visible_watched_channels,
)
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
        self.id = 42
        self.guild = None
        self.send = AsyncMock()


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
        requester.guild = guild_obj
        guild_obj.fetch_member = AsyncMock(return_value=requester)
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
    requester = Requester(hidden={13})
    texts = run_command(store, here, guild(1, channels), requester)
    assert texts == [DM_DELIVERED_NOTICE]
    requester.send.assert_awaited_once()
    assert requester.send.await_args.args[0] == (
        "📡👀 지금 본인이 보고 있는 채널을 알려주겠소\n"
        " - 💬 잡담\n - 💬 개발\n - 💬 기획\n✅ 이상이오. 🫡"
    )
    assert "channel_list_delivery outcome=ok" in caplog.text
    assert "count=" not in caplog.text
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
    assert run_command(store, here, guild(1, [here]), Requester()) == [DM_FAILED_NOTICE]


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
        requester = Requester()
        current_guild = guild(1, [here])
        requester.guild = current_guild
        current_guild.fetch_member = AsyncMock(return_value=requester)
        workflow = SimpleNamespace(states=states, run=AsyncMock(), shutdown=AsyncMock())
        client = YoYackClient(watch_store=store, summary_workflow=workflow)  # type: ignore[arg-type]
        try:
            await client.on_message(event("!!요약좀 채널", here, current_guild, requester))
        finally:
            await client.close()
        workflow.run.assert_not_awaited()
        assert here.send.await_args.args[0] == DM_DELIVERED_NOTICE
        assert requester.send.await_args.args[0].endswith(" - 💬 잡담\n✅ 이상이오. 🫡")
        assert (await states.active(1, 11)) is not None

    asyncio.run(scenario())


def test_gateway_sends_split_parts_in_order_without_mentions() -> None:
    from yoyackbot.config import Settings

    async def scenario() -> list[object]:
        names = [f"채널{index:02d}" + "나" * 40 for index in range(30)]
        channels = [text_channel(100 + i, name, i) for i, name in enumerate(names)]
        store = MemoryWatchStore()
        store.replace(1, frozenset(channel.id for channel in channels))
        here = channels[0]
        requester = Requester()
        current_guild = guild(1, channels)
        requester.guild = current_guild
        current_guild.fetch_member = AsyncMock(return_value=requester)
        settings = Settings.from_environment({
            "DISCORD_BOT_TOKEN": "x", "YOYACK_DISCORD_MESSAGE_LIMIT": "400",
        })
        client = YoYackClient(watch_store=store, settings=settings,
                              summary_workflow=NoWorkflow())  # type: ignore[arg-type]
        try:
            await client.on_message(event("!!요약좀 채널", here, current_guild, requester))
        finally:
            await client.close()
        assert [call.args[0] for call in here.send.await_args_list] == [DM_DELIVERED_NOTICE]
        calls = requester.send.await_args_list
        assert len(calls) > 1 and all(len(call.args[0]) <= 400 for call in calls)
        assert all(call.kwargs["allowed_mentions"].to_dict()["parse"] == [] for call in calls)
        assert all(call.kwargs["suppress_embeds"] is True for call in calls)
        assert current_guild.fetch_member.await_count == len(calls)
        lines = "\n".join(call.args[0] for call in calls).splitlines()
        assert lines[0] == "📡👀 지금 본인이 보고 있는 채널을 알려주겠소" and lines[-1] == "✅ 이상이오. 🫡"
        assert lines[1:-1] == [f" - 💬 {name}" for name in names]
        return calls

    asyncio.run(scenario())


def private_delivery_fixture():
    channels = [
        text_channel(100 + index, f"비공개{index:02d}-" + "나" * 40, index)
        for index in range(12)
    ]
    store = MemoryWatchStore()
    store.replace(1, frozenset(channel.id for channel in channels))
    requester = Requester()
    current_guild = guild(1, channels)
    requester.guild = current_guild
    current_guild.fetch_member = AsyncMock(return_value=requester)
    return channels, store, requester, current_guild


@pytest.mark.parametrize("change", [
    "leave", "role", "origin_permission", "watch", "origin_watch", "rename", "guild", "dm",
])
def test_private_delivery_stops_before_stale_second_part(change: str, caplog) -> None:
    async def scenario() -> None:
        channels, store, requester, current_guild = private_delivery_fixture()

        async def send_first_then_change(*_args, **_kwargs) -> None:
            if change == "leave":
                current_guild.fetch_member.side_effect = RuntimeError("private member detail")
            elif change == "role":
                requester.hidden = {channels[-1].id}
            elif change == "origin_permission":
                requester.hidden = {channels[0].id}
            elif change in {"watch", "origin_watch"}:
                removed = channels[-1] if change == "watch" else channels[0]
                store.replace(1, frozenset(channel.id for channel in channels if channel != removed))
            elif change == "rename":
                channels[-1].name = "새로운-비공개-이름"
            elif change == "guild":
                moved = Requester()
                moved.guild = SimpleNamespace(id=2)
                current_guild.fetch_member.return_value = moved
            elif change == "dm":
                requester.send.side_effect = RuntimeError("private DM error detail")

        requester.send.side_effect = send_first_then_change
        notice = await deliver_channel_list(
            current_guild, requester, store, origin_channel_id=channels[0].id, limit=200,
        )
        assert notice == DM_FAILED_NOTICE
        # A transport error can occur while attempting part two; all other changes
        # are detected before the second DM send starts.
        assert requester.send.await_count == (2 if change == "dm" else 1)
        assert current_guild.fetch_member.await_count == 2
        assert all(channel.send.await_count == 0 for channel in channels)
        assert "private" not in caplog.text
        assert "비공개" not in notice and "비공개" not in caplog.text

    asyncio.run(scenario())


def test_current_member_roles_replace_the_original_author_snapshot() -> None:
    async def scenario() -> None:
        channels, store, requester, current_guild = private_delivery_fixture()
        current_member = Requester(hidden={channels[-1].id})
        current_member.guild = current_guild
        current_guild.fetch_member.return_value = current_member
        result = await deliver_channel_list(
            current_guild, requester, store, origin_channel_id=channels[0].id,
        )
        assert result == DM_DELIVERED_NOTICE
        requester.send.assert_not_awaited()
        body = "\n".join(call.args[0] for call in current_member.send.await_args_list)
        assert channels[0].name in body
        assert channels[-1].name not in body

    asyncio.run(scenario())


def test_dm_failure_has_only_a_generic_public_notice(caplog) -> None:
    channels, store, requester, current_guild = private_delivery_fixture()
    requester.send.side_effect = RuntimeError("private DM transport detail")
    notices = run_command(store, channels[0], current_guild, requester)
    assert notices == [DM_FAILED_NOTICE]
    requester.send.assert_awaited_once()
    assert all(channel.name not in notices[0] for channel in channels)
    assert "private DM transport detail" not in caplog.text


def test_wrong_requester_guild_fails_before_reading_or_sending() -> None:
    async def scenario() -> None:
        channels, store, requester, current_guild = private_delivery_fixture()
        requester.guild = SimpleNamespace(id=2)
        notice = await deliver_channel_list(
            current_guild, requester, store, origin_channel_id=channels[0].id,
        )
        assert notice == DM_FAILED_NOTICE
        current_guild.fetch_member.assert_not_awaited()
        requester.send.assert_not_awaited()

    asyncio.run(scenario())


def test_delivery_cancellation_propagates() -> None:
    async def scenario() -> None:
        channels, store, requester, current_guild = private_delivery_fixture()
        requester.send.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await deliver_channel_list(
                current_guild, requester, store, origin_channel_id=channels[0].id,
            )
        requester.send.assert_awaited_once()

    asyncio.run(scenario())
