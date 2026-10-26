"""1.4.4-P2: the 22:30 review with each person's protein/sugar/exercise tally (T144-P2-A/B)."""

import asyncio
import json
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from test_p143_diet_judge import GOOD, NOW, line, photo, post, run_judge
from test_p143_diet_schedule import CHANNEL, A, B, World, at, message

from yoyackbot.diet import DailyRecord, SQLiteDietStore
from yoyackbot.diet_judge import (
    DIET_PROMPT,
    ESTIMATE_NOTE,
    FAILED,
    NOBODY,
    PersonTally,
    build_input,
    compose,
    judge_day,
    parse_answer,
    tally_line,
)
from yoyackbot.diet_schedule import DietPost
from yoyackbot.notices import unmatched

GYM = 11


def gym_post(author, text, minutes=0, photos=()):
    return DietPost(author, text, tuple(photos), NOW + timedelta(minutes=minutes), "exercise")


def with_gym(world, valid=True):
    """A second text channel for exercise posts."""
    gym = SimpleNamespace(id=GYM, send=AsyncMock(), history=world.history_of("gym"))
    channels = {CHANNEL: world.channel, GYM: gym}
    world.guild.get_channel = channels.get
    return gym


# T144-P2-A ------------------------------------------------------------------------------

def test_exercise_posts_join_as_their_own_lines() -> None:
    diet = asyncio.run(build_input(
        [post(A, "닭가슴살", minutes=5)],
        [gym_post(B, "러닝 5km", 1), gym_post(A, "", 9, [photo("run.png", content=b"R",
                                                                content_type="image/png")])],
    ))
    assert diet.people == [B, A]                         # by first post, either channel
    lines = [json.loads(x) for x in diet.data.decode().splitlines()]
    assert [(x["type"], x["person"], x.get("text"), x.get("images")) for x in lines[2:]] == [
        ("exercise_post", "P1", "러닝 5km", None), ("post", "P2", "닭가슴살", None),
        ("exercise_post", "P2", None, [1])]
    assert "exercise_post" in DIET_PROMPT and "protein_g" in DIET_PROMPT and "null" in DIET_PROMPT


def test_the_scheduler_reads_a_separate_exercise_channel(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    gym_messages = [message(B, "스쿼트 5세트", when=at(20)), message(A, "!!명령", when=at(20, 5))]

    def history_of(_name):
        async def history(*, after, before, limit, oldest_first):
            for item in gym_messages:
                if after < item.created_at < before:
                    yield item
        return history

    world.history_of = history_of
    with_gym(world)
    world.store.set_exercise_channel(1, GYM)
    world.messages = [message(A, "김밥", when=at(21, 5))]
    world.tick(at(21), at(22), at(22, 30))
    (exercise, day), = world.judged_extra
    assert day == "2026-10-18"
    assert [(p.author_id, p.text, p.kind) for p in exercise] == [(B, "스쿼트 5세트", "exercise")]
    assert [p.kind for p in world.judged[0][2]] == ["diet"]


def test_no_separate_exercise_posts_by_default_or_when_unusable(tmp_path, monkeypatch) -> None:
    world = World(tmp_path, monkeypatch)
    world.messages = [message(A, "김밥", when=at(21, 5))]
    world.tick(at(22, 30))                               # no exercise channel: the diet channel
    world.store.set_exercise_channel(1, CHANNEL)         # the same channel: read once
    world.tick(at(22, 30, day=19))
    world.store.set_exercise_channel(1, GYM)             # a channel that is gone
    world.tick(at(22, 30, day=20))
    assert world.judged_extra == [([], "2026-10-18"), ([], "2026-10-19"), ([], "2026-10-20")]
    assert len(world.judged) == 3


def test_tally_lines_and_the_estimate_note() -> None:
    assert tally_line(PersonTally("x", 60, 25, "샐러드", "러닝 30분")) == \
        "└ 🥩 단백질 약 60g · 🍬 당류 약 25g · 🏃 러닝 30분"
    assert tally_line(PersonTally("x", None, 8, "식단 기록 없음", None)) == "└ 🍬 당류 약 8g"
    assert tally_line(PersonTally("x", None, None, "식단 기록 없음", None)) is None
    text = compose(1, [A], [PersonTally("x", 0, 0, "물", None)], "끝.", [])[0]
    assert text.endswith(ESTIMATE_NOTE) and "└ 🥩 단백질 약 0g · 🍬 당류 약 0g" in text
    assert unmatched(ESTIMATE_NOTE) == []


def test_parsed_tallies_keep_numbers_and_trim_summaries() -> None:
    answer = "\n".join([line("P1", "하나", 0, 400, "가" * 90, "나" * 90),
                        line("P2", "둘", None, None, "", None), json.dumps({"verdict": "끝."})])
    (first, second), verdict = parse_answer(answer, 2)
    assert (first.protein_g, first.sugar_g, len(first.foods), len(first.exercise)) == (0, 400, 80, 80)
    assert (second.protein_g, second.sugar_g, second.foods, second.exercise) == \
        (None, None, "식단 기록 없음", None)
    assert verdict == "끝."
    assert parse_answer(answer.replace('"exercise": null', '"exercise": "<@1> 러닝"'), 2) is None


# T144-P2-B ------------------------------------------------------------------------------

def judged_and_saved(answers, posts, exercise=(), fail_save=False):
    channel = SimpleNamespace(send=AsyncMock())
    saved = []
    queue = list(answers)

    async def ask(prompt, diet):
        return queue.pop(0)

    async def save(records):
        if fail_save:
            raise OSError("disk full")
        saved.extend(records)

    outcome = asyncio.run(judge_day(1, channel, [], posts, tone=None, ask=ask,
                                    exercise_posts=exercise, save=save))
    for call in channel.send.await_args_list:
        mentions = call.kwargs["allowed_mentions"]
        assert not mentions.users and not mentions.roles and not mentions.everyone
    return outcome, [call.args[0] for call in channel.send.await_args_list], saved


def test_each_person_is_saved_after_the_post(caplog) -> None:
    caplog.set_level(logging.INFO)
    outcome, sent, saved = judged_and_saved([GOOD], [post(A, "샐러드"), post(B, "라면", minutes=1)])
    assert outcome == "posted" and "└ 🥩 단백질 약 25g · 🍬 당류 약 12g · 🏃 러닝 20분" in sent[0]
    assert saved == [DailyRecord(A, 25, 12, "샐러드", "러닝 20분"), DailyRecord(B, 10, 5, "라면", None)]
    assert "샐러드" not in caplog.text and "러닝" not in caplog.text


def test_a_failed_save_keeps_the_post(caplog) -> None:
    outcome, sent, saved = judged_and_saved([GOOD], [post(A, "샐러드"), post(B, "라면", minutes=1)],
                                            fail_save=True)
    assert outcome == "posted" and sent[0].startswith("🐷 **오늘의 식단 평가**") and saved == []
    assert "diet_daily_save_failed" in caplog.text


def test_nothing_is_saved_when_the_review_fails() -> None:
    outcome, sent, saved = judged_and_saved(["엉망", "또 엉망"], [post(A, "샐러드")])
    assert (outcome, sent, saved) == ("failed", [FAILED], [])


def test_exercise_only_days_are_reviewed_not_nobody() -> None:
    answer = "\n".join([line("P1", "먹은 건 안 보이고 땀만 보이오.", None, None, "식단 기록 없음",
                             "러닝 5km"), json.dumps({"verdict": "운동만 했구려."}, ensure_ascii=False)])
    outcome, sent, saved = judged_and_saved([answer], [], [gym_post(A, "러닝 5km")])
    assert outcome == "posted" and NOBODY not in sent[0] and "└ 🏃 러닝 5km" in sent[0]
    assert saved == [DailyRecord(A, None, None, "식단 기록 없음", "러닝 5km")]
    outcome, sent, _ = run_judge([], [])
    assert outcome == "nobody"


def test_the_client_saves_the_day(tmp_path, monkeypatch) -> None:
    from test_p140_tone_notices import toned_client

    class Engine:
        async def diet_review(self, prompt, data, photos):
            return GOOD

    client, _tones = toned_client(tmp_path, monkeypatch, None)
    client.summary_workflow.engine = Engine()
    store = SQLiteDietStore(client.settings.database_path)
    client.diets = store
    channel = SimpleNamespace(send=AsyncMock())

    async def scenario():
        try:
            return await client._diet_judge(
                SimpleNamespace(id=1), channel, 70, [], [post(A, "샐러드")],
                exercise_posts=[gym_post(B, "러닝 20분", 1)], day="2026-10-26")
        finally:
            await client.close()

    assert asyncio.run(scenario()) == "posted"
    week = store.week(1, "2026-10-20", "2026-10-26")
    assert week == {A: [("2026-10-26", DailyRecord(A, 25, 12, "샐러드", "러닝 20분"))],
                    B: [("2026-10-26", DailyRecord(B, 10, 5, "라면", None))]}
