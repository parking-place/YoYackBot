"""1.4.4-P3: the Sunday advice from the week's saved tallies (T144-P3-A/B)."""

import asyncio
import json
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_p143_diet_schedule import KST, ROLE, A, B, C, D, E, World, at

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.diet import DailyRecord
from yoyackbot.diet_schedule import DietScheduler
from yoyackbot.diet_week import (
    EMPTY,
    FAILED,
    NOTE,
    WEEK_PEOPLE,
    WEEK_PROMPT,
    WeekStats,
    advise_week,
    build_input,
    compose,
    parse_advice,
    stats_line,
    week_prompt,
    week_stats,
)
from yoyackbot.notices import BOOK, unmatched
from yoyackbot.tone_presets import BY_KEY

GYM_ROLE = 71
SUNDAY, SATURDAY, MONDAY = 18, 17, 19                     # 2026-10-18 is a Sunday


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


def advice_line(person, text="고기를 끼니마다 손바닥만큼 더 드시오."):
    return json.dumps({"person": person, "advice": text}, ensure_ascii=False)


def record(user, protein=30, sugar=10, foods="샐러드", exercise=None):
    return DailyRecord(user, protein, sugar, foods, exercise)


class AdviceWorld(World):
    def __init__(self, tmp_path, monkeypatch):
        super().__init__(tmp_path, monkeypatch)
        self.order = []
        self.advised = []
        judge = self.scheduler.judge

        async def judged(*args, **kwargs):
            self.order.append("judge")
            return await judge(*args, **kwargs)

        async def advise(guild, channel, records, members):
            self.order.append("week")
            self.advised.append((channel, records, members))
            return "posted"

        self.advise = advise
        self.scheduler = DietScheduler(self.store, lambda gid: self.guild if gid == 1 else None,
                                       zone=KST, judge=judged, advise=advise)


# T144-P3-A ------------------------------------------------------------------------------

def test_the_week_follows_the_sunday_review_once(tmp_path, monkeypatch) -> None:
    world = AdviceWorld(tmp_path, monkeypatch)
    world.tick(at(22, 30, SATURDAY), at(23, 50, SATURDAY))
    assert world.advised == [] and world.order == ["judge"]
    world.tick(at(22, 29, SUNDAY))
    assert world.advised == []                           # not before the review
    world.tick(at(22, 30, SUNDAY), at(22, 31, SUNDAY), at(23, 59, SUNDAY))
    assert world.order == ["judge", "judge", "week"] and world.advised[0][0] is world.channel
    assert world.store.week_done(1, "2026-10-12") == "posted"
    again = DietScheduler(world.store, lambda gid: world.guild, zone=KST, judge=None, advise=world.advise)
    asyncio.run(again.tick(at(23, 50, SUNDAY)))
    asyncio.run(again.tick(at(22, 30, MONDAY)))
    assert len(world.advised) == 1


def test_a_late_sunday_still_advises_until_midnight(tmp_path, monkeypatch) -> None:
    world = AdviceWorld(tmp_path, monkeypatch)
    world.tick(at(23, 55, SUNDAY))
    assert world.order == ["judge", "week"]
    (tmp_path / "late").mkdir()
    late = AdviceWorld(tmp_path / "late", monkeypatch)
    late.tick(at(0, 10, MONDAY), at(22, 30, MONDAY))       # Sunday was missed: no advice on Monday
    assert late.advised == [] and late.store.week_done(1, "2026-10-12") is None


def test_no_advise_hook_claims_nothing(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.tick(at(22, 30, SUNDAY))
    assert world.store.week_done(1, "2026-10-12") is None


def test_people_are_the_recorders_and_both_roles(tmp_path, monkeypatch) -> None:
    world = AdviceWorld(tmp_path, monkeypatch)
    gym_role = SimpleNamespace(id=GYM_ROLE)
    role = world.guild.get_role(ROLE)
    world.guild.get_role = {ROLE: role, GYM_ROLE: gym_role}.get

    async def fetch_members(limit=None):
        yield SimpleNamespace(id=A, bot=False, roles=[role])
        yield SimpleNamespace(id=E, bot=False, roles=[gym_role])
        yield SimpleNamespace(id=900, bot=True, roles=[role, gym_role])

    world.guild.fetch_members = fetch_members
    world.store.set_exercise_role(1, GYM_ROLE)
    stamp = at(22, 30, SUNDAY)
    world.store.save_daily(1, "2026-10-11", [record(C)], stamp)          # last week: left out
    world.store.save_daily(1, "2026-10-12", [record(B, 40)], stamp)
    world.store.save_daily(1, "2026-10-18", [record(B, 20), record(D, None, None, "식단 기록 없음", "러닝")],
                           stamp)
    world.tick(at(22, 30, SUNDAY))
    (_channel, records, members), = world.advised
    assert members == [A, E] and sorted(records) == [B, D]
    assert records[B] == [("2026-10-12", record(B, 40)), ("2026-10-18", record(B, 20))]


def test_problems_are_recorded_for_the_week(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    world = AdviceWorld(tmp_path, monkeypatch)
    world.guild.get_channel = lambda _cid: None
    world.tick(at(22, 30, SUNDAY))
    assert world.advised == [] and world.store.week_done(1, "2026-10-12") == "no_channel"
    assert "diet_run stage=week outcome=no_channel" in caplog.text


def test_the_bot_works_out_each_week() -> None:
    b = [("2026-10-12", record(B, 40, 10, "닭가슴살", "러닝 20분")), ("2026-10-13", record(B, None, 21)),
         ("2026-10-14", record(B, 25, None, "식단 기록 없음", "수영"))]
    stats = week_stats({B: b, D: [("2026-10-18", record(D, None, None, "식단 기록 없음", None))]}, [A, B])
    assert [item.user_id for item in stats] == [B, D, A]               # more records first
    first = stats[0]
    assert (first.recorded_days, first.meal_days, first.exercise_days) == (3, 3, 2)
    assert (first.average("protein_g"), first.average("sugar_g")) == (32, 16)
    assert stats[1].meal_days == 0 and stats[1].average("protein_g") is None
    lines = [json.loads(x) for x in build_input(stats).decode().splitlines()]
    assert lines[0] == {"type": "person", "person": "P1", "recorded_days": 3, "meal_days": 3,
                        "exercise_days": 2, "avg_protein_g": 32, "avg_sugar_g": 16, "days": [
                            {"day": "월", "foods": "닭가슴살", "protein_g": 40, "sugar_g": 10,
                             "exercise": "러닝 20분"},
                            {"day": "화", "foods": "샐러드", "protein_g": None, "sugar_g": 21, "exercise": None},
                            {"day": "수", "foods": "식단 기록 없음", "protein_g": 25, "sugar_g": None,
                             "exercise": "수영"}]}
    assert lines[2]["recorded_days"] == 0 and lines[2]["days"] == []
    assert b"502" not in build_input(stats) and b"501" not in build_input(stats)


def test_the_prompt_asks_for_practical_advice_in_the_tone() -> None:
    for word in ("실질적인 훈수", "단백질", "주 150분", "recorded_days가 0", "진단", "P 번호", '"advice"'):
        assert word in WEEK_PROMPT
    assert week_prompt(None).startswith(WEEK_PROMPT) and "하오체" in week_prompt(None)
    toned = week_prompt(BY_KEY["mz"].tone + " «`»", retry=True)
    assert BY_KEY["mz"].tone in toned and "«`»" not in toned and toned.endswith("다시\n쓰시오.")


# T144-P3-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("answer", "ok"), [
    ("\n".join([advice_line("P1"), advice_line("P2", "기록부터 올리시오.")]), True),
    ("```json\n" + "\n".join([advice_line("P1"), advice_line("P2")]) + "\n```", True),
    (advice_line("P1"), False),                                          # a person missing
    ("\n".join([advice_line("P1"), advice_line("P1"), advice_line("P2")]), False),
    ("\n".join([advice_line("P1"), advice_line("P3")]), False),
    ("\n".join([advice_line("P1", "가" * 201), advice_line("P2")]), False),
    ("\n".join([advice_line("P1", ""), advice_line("P2")]), False),
    ("\n".join([advice_line("P1", "병신같이 먹었소"), advice_line("P2")]), False),
    ("\n".join([advice_line("P1", "그러다 뚱뚱해지오"), advice_line("P2")]), False),
    ("\n".join([advice_line("P1", "<@1> 처럼 드시오"), advice_line("P2")]), False),
    ("\n".join([advice_line("P1", "P2처럼 드시오"), advice_line("P2")]), False),
    ("P1: 고기 더\nP2: 기록", False),
    ("{깨진\n" + advice_line("P1"), False),
])
def test_advice_is_parsed_and_checked(answer, ok) -> None:
    assert (parse_advice(answer, 2) is not None) is ok


def test_the_post_layout() -> None:
    stats = [WeekStats(B, (("2026-10-12", record(B, 52, 31, "닭", "러닝")), ("2026-10-13", record(B)))),
             WeekStats(A, ())]
    assert stats_line(stats[0]) == "└ 🥩 평균 41g · 🍬 평균 20g · 🏃 1일 · 🍽️ 2일 기록"
    assert stats_line(stats[1]) == "└ 📭 이번 주 기록 없음"
    assert stats_line(WeekStats(A, (("2026-10-12", record(A, None, None, "식단 기록 없음", "요가")),))) == \
        "└ 🏃 1일 · 🍽️ 1일 기록"
    parts = compose(1, stats, ["단백질을 더 드시오.", "기록부터 올리시오."])
    assert parts == [(f"📅 **이번 주 식단·운동 훈수**\n\n<@{B}> 단백질을 더 드시오.\n"
                      "└ 🥩 평균 41g · 🍬 평균 20g · 🏃 1일 · 🍽️ 2일 기록\n"
                      f"<@{A}> 기록부터 올리시오.\n└ 📭 이번 주 기록 없음\n\n{NOTE}")]
    assert [x for x in unmatched(parts[0]) if not x.startswith(("<@", "└ "))] == []
    assert unmatched(FAILED) == [] and unmatched(EMPTY) == []
    many = compose(1, [WeekStats(n, ()) for n in range(1, 41)], ["가" * 190] * 40)
    assert len(many) > 1 and all(len(part) <= 1900 for part in many)


def run_week(answers, records, members=()):
    channel = SimpleNamespace(send=AsyncMock())
    asked = []

    async def ask(prompt, data):
        asked.append((prompt, data))
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    outcome = asyncio.run(advise_week(1, channel, records, list(members), tone=None, ask=ask))
    for call in channel.send.await_args_list:
        mentions = call.kwargs["allowed_mentions"]
        assert not mentions.users and not mentions.roles and not mentions.everyone
    return outcome, [call.args[0] for call in channel.send.await_args_list], asked


WEEK = {B: [("2026-10-12", record(B, 20, 40, "도넛", None))]}
GOOD = "\n".join([advice_line("P1", "도넛 대신 그릭요거트를 드시오."), advice_line("P2", "기록부터 올리시오.")])


def test_advice_retries_posts_and_fails_quietly(caplog) -> None:
    caplog.set_level(logging.INFO)
    outcome, sent, asked = run_week(["엉망", GOOD], WEEK, [A])
    assert outcome == "posted" and len(asked) == 2 and asked[1][0].endswith("다시\n쓰시오.")
    assert isinstance(asked[0][1], bytes)                               # text only
    assert sent[0].startswith("📅 **이번 주 식단·운동 훈수**") and f"<@{B}> 도넛 대신" in sent[0]
    assert f"<@{A}> 기록부터 올리시오.\n└ 📭 이번 주 기록 없음" in sent[0]
    assert run_week(["엉망", "또 엉망"], WEEK, [A])[:2] == ("failed", [FAILED])
    assert run_week([RuntimeError("down")], WEEK, [A])[:2] == ("failed", [FAILED])
    assert "도넛" not in caplog.text and "요거트" not in caplog.text
    assert "diet_week people=2 recorded=1 dropped=0 calls=2 ok=True" in caplog.text


def test_no_records_need_no_model() -> None:
    assert run_week([], {}, [A, B]) == ("empty", [EMPTY], [])
    assert run_week([], {}, []) == ("nobody", [], [])


def test_the_week_is_capped(caplog) -> None:
    caplog.set_level(logging.INFO)
    members = range(1000, 1000 + WEEK_PEOPLE + 5)
    answer = "\n".join(advice_line(f"P{n}") for n in range(1, WEEK_PEOPLE + 1))
    outcome, sent, asked = run_week([answer], WEEK, members)
    assert outcome == "posted" and f"<@{B}>" in sent[0]                  # recorders first
    assert len(asked[0][1].decode().splitlines()) == WEEK_PEOPLE
    assert "dropped=6" in caplog.text


def test_the_engine_sends_no_photos(tmp_path) -> None:
    seen = []

    @dataclass(frozen=True)
    class Runner:
        contract: object
        timeout_seconds: float = 120

        async def execute(self, workspace, prompt):
            seen.append((list(workspace.images), prompt))
            workspace.close()
            return GOOD

    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_INPUT_DIR": str(tmp_path / "in")})
    engine = CodexSummaryEngine(settings, Runner(SimpleNamespace(reasoning_effort="medium")))
    assert asyncio.run(engine.diet_advice("지시", b'{"type":"person","person":"P1"}\n')) == GOOD
    assert seen[0][0] == [] and "<<<자료" in seen[0][1]


def test_the_client_advises_with_its_engine(tmp_path, monkeypatch) -> None:
    from test_p140_tone_notices import toned_client
    calls = []

    class Engine:
        async def diet_advice(self, prompt, data):
            calls.append(prompt)
            return GOOD

    client, tones = toned_client(tmp_path, monkeypatch, None)
    client.summary_workflow.engine = Engine()
    tones.save(1, BY_KEY["mz"].tone, expected_version=0)
    channel = SimpleNamespace(send=AsyncMock())

    async def scenario():
        try:
            return await client._diet_week(SimpleNamespace(id=1), channel, WEEK, [A])
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "posted"
    assert BY_KEY["mz"].tone in calls[0]
    assert channel.send.await_args.args[0].startswith("📅 **이번 주 식단·운동 훈수**")


def test_the_client_without_an_engine_says_so(tmp_path, monkeypatch) -> None:
    from test_p140_tone_notices import toned_client
    client, _tones = toned_client(tmp_path, monkeypatch, None)
    channel = SimpleNamespace(send=AsyncMock())

    async def scenario():
        try:
            return await client._diet_week(SimpleNamespace(id=1), channel, WEEK, [A])
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "unavailable"
    assert channel.send.await_args.args[0] == FAILED
