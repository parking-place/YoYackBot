"""1.4.3-P2: 21:00 call, 22:00 nag, 22:30 judge — once a day each (T143-P2-A/B)."""

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import discord
import pytest

from yoyackbot.diet import SQLiteDietStore
from yoyackbot.diet_schedule import DietScheduler
from yoyackbot.notices import unmatched
from yoyackbot.watch_store import SQLiteWatchStore

KST = ZoneInfo("Asia/Seoul")
ROLE, CHANNEL = 70, 10
A, B, C, D, E, BOT = 501, 502, 503, 504, 505, 900   # A–D have the role; E does not


def at(hour, minute=0, day=18):
    return datetime(2026, 10, day, hour, minute, tzinfo=KST).astimezone(UTC)


def message(author, content="", attachments=(), when=None, bot=False):
    return SimpleNamespace(author=SimpleNamespace(id=author, bot=bot), content=content,
                           attachments=list(attachments), created_at=when)


class World:
    def __init__(self, tmp_path, monkeypatch, *, valid=True):
        path = tmp_path / "db.sqlite"
        SQLiteWatchStore(path)
        self.store = SQLiteDietStore(path)
        self.store.set_channel(1, CHANNEL)
        self.store.set_role(1, ROLE)
        self.messages = []
        self.channel = SimpleNamespace(id=CHANNEL, send=AsyncMock(), history=self.history)
        role = SimpleNamespace(id=ROLE)
        people = [SimpleNamespace(id=m, bot=False, roles=[role]) for m in (A, B, C, D)]
        people += [SimpleNamespace(id=E, bot=False, roles=[]), SimpleNamespace(id=BOT, bot=True, roles=[role])]

        async def fetch_members(limit=None):
            for person in people:
                yield person

        self.guild = SimpleNamespace(
            id=1, get_channel=lambda cid: self.channel if cid == CHANNEL else None,
            get_role=lambda rid: role if rid == ROLE else None, fetch_members=fetch_members,
        )
        monkeypatch.setattr("yoyackbot.diet_schedule.valid_channel", lambda *_: valid)
        self.judged = []

        async def judge(guild, channel, role_id, missing, posts):
            self.judged.append((role_id, list(missing), posts))
            return "posted"

        self.scheduler = DietScheduler(self.store, lambda gid: self.guild if gid == 1 else None,
                                       zone=KST, judge=judge)

    async def history(self, *, after, before, limit, oldest_first):
        assert oldest_first and limit == 2000
        for item in self.messages:
            if after < item.created_at < before:
                yield item

    def tick(self, *times):
        for now in times:
            asyncio.run(self.scheduler.tick(now))

    def sent(self):
        return [call.args[0] for call in self.channel.send.await_args_list]


# T143-P2-A ------------------------------------------------------------------------------

def test_the_call_goes_out_once_at_nine_pm(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.tick(at(20, 59))
    assert world.sent() == []
    world.tick(at(21, 0), at(21, 1), at(21, 30))
    assert world.sent() == [f"🐷 <@&{ROLE}> 오늘 식단을 올리시오! 🍽️"]
    mentions = world.channel.send.await_args.kwargs["allowed_mentions"]
    assert [r.id for r in mentions.roles] == [ROLE] and not mentions.users and not mentions.everyone
    assert world.store.done(1, "2026-10-18") == {"call": "posted"}


def test_the_nag_calls_only_those_who_posted_nothing_today(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.messages = [
        message(C, "어제 먹은 거", when=at(23, day=17)),                 # yesterday
        message(A, "닭가슴살 샐러드", when=at(12)),
        message(B, "", attachments=[SimpleNamespace(filename="밥.jpg")], when=at(21, 30)),
        message(D, "!!요약좀", when=at(21, 40)),                         # a command
        message(E, "나는 역할이 없지만 올림", when=at(21, 45)),
        message(BOT, "봇 글", when=at(21, 50), bot=True),
    ]
    world.tick(at(21), at(22))
    nag = world.sent()[1]
    assert nag == f"🐷 <@{C}> <@{D}> 아직 식단이 안 올라왔소! 30분 남았소. ⏰"
    mentions = world.channel.send.await_args.kwargs["allowed_mentions"]
    assert sorted(user.id for user in mentions.users) == [C, D] and not mentions.roles


def test_no_nag_when_everyone_posted_and_the_judge_sees_role_posts_only(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.messages = [message(m, f"{m}의 식단", when=at(21, 10)) for m in (A, B, C, D, E)]
    world.tick(at(21), at(22), at(22, 29))
    assert len(world.sent()) == 1 and world.store.done(1, "2026-10-18")["nag"] == "all_posted"
    world.tick(at(22, 30), at(22, 31))
    (role_id, missing, posts), = world.judged
    assert role_id == ROLE and missing == [] and sorted(p.author_id for p in posts) == [A, B, C, D]
    assert world.store.done(1, "2026-10-18")["judge"] == "posted"


def test_judge_gets_the_missing_people(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.messages = [message(A, "라면", when=at(21, 5))]
    world.tick(at(21), at(22), at(22, 30))
    assert world.judged[0][1] == [B, C, D] and [p.text for p in world.judged[0][2]] == ["라면"]


# T143-P2-B ------------------------------------------------------------------------------

def test_a_restart_never_repeats_a_step(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.tick(at(21), at(22), at(22, 30))
    again = DietScheduler(world.store, lambda gid: world.guild, zone=KST, judge=None)
    asyncio.run(again.tick(at(22, 40)))
    assert len(world.sent()) == 2 and len(world.judged) == 1


@pytest.mark.parametrize(("start", "outcomes", "sent"), [
    (at(21, 49), {"call": "posted"}, 1),
    (at(21, 50), {"call": "skipped_late"}, 0),
    (at(22, 55), {"call": "skipped_late", "nag": "skipped_late", "judge": "posted"}, 0),
    (at(23, 59), {"call": "skipped_late", "nag": "skipped_late", "judge": "posted"}, 0),
])
def test_a_late_start_keeps_to_the_grace_windows(tmp_path, monkeypatch, start, outcomes, sent) -> None:
    world = World(tmp_path, monkeypatch)
    world.tick(start)
    assert world.store.done(1, "2026-10-18") == outcomes and len(world.sent()) == sent


def test_a_new_day_starts_again(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.tick(at(21), at(22), at(22, 30))
    world.tick(at(0, 1, day=19), at(20, 59, day=19))
    assert world.store.done(1, "2026-10-19") == {}
    world.tick(at(21, day=19))
    assert world.store.done(1, "2026-10-19") == {"call": "posted"}


def test_problems_are_recorded_without_posting(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    world = World(tmp_path, monkeypatch, valid=False)
    world.tick(at(21))
    assert world.sent() == [] and world.store.done(1, "2026-10-18") == {"call": "no_channel"}
    other = tmp_path / "other"
    other.mkdir()
    broken = World(other, monkeypatch)
    broken.channel.send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "x")
    broken.tick(at(21))
    assert broken.store.done(1, "2026-10-18") == {"call": "send_failed"}
    third = tmp_path / "third"
    third.mkdir()
    gone = World(third, monkeypatch)
    gone.guild.get_role = lambda rid: None
    gone.tick(at(21))
    assert gone.store.done(1, "2026-10-18") == {"call": "no_role"}
    assert "diet_run stage=call outcome=no_channel" in caplog.text and "<@" not in caplog.text


def test_unconfigured_servers_are_left_alone(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.store.set_role(1, None)
    world.tick(at(21), at(22), at(22, 30))
    assert world.sent() == [] and world.store.done(1, "2026-10-18") == {}


def test_texts_are_in_the_catalog() -> None:
    for text in (f"🐷 <@&{ROLE}> 오늘 식단을 올리시오! 🍽️",
                 f"🐷 <@{A}> <@{B}> 외 3명 아직 식단이 안 올라왔소! 30분 남았소. ⏰"):
        assert unmatched(text) == [], text


def test_the_client_loop_ticks_only_when_connected(tmp_path, monkeypatch) -> None:
    from test_p140_audit_log import client_with
    client, _home, _channel = client_with(tmp_path, monkeypatch, channel=None)
    ticks = []

    async def tick(now):
        ticks.append(now)

    client.diet_scheduler.tick = tick

    async def scenario():
        try:
            task = asyncio.create_task(client._diet_loop(interval=0.01))
            await asyncio.sleep(0.05)
            assert ticks == []
            client.ready_event.set()
            await asyncio.sleep(0.05)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            await client.close()

    asyncio.run(scenario())
    assert ticks
