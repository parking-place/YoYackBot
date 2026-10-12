"""1.4.2-P3: `/셀프디스` from the caller's own words only (T142-P3-A/B)."""

import asyncio
import json
import logging
from datetime import timedelta

import pytest
from test_p130_idiom import NOW, Runner, context, mid
from test_p134_idiom_slash import interaction, posted, private

from yoyackbot import self_roast
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.domain import MessageRecord
from yoyackbot.notices import BOOK, unmatched
from yoyackbot.tone import SQLiteToneStore
from yoyackbot.tone_presets import BY_KEY

CALLER = 9          # the fixture's third author writes messages 2, 5, 8 … ("대화 n")
JAB = "점심 메뉴만 열 번 묻고 결정은 남에게 넘기는 재주가 놀랍구려."


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


def roast(ctx, *calls):
    command = ctx.client.tree.get_command("셀프디스")

    async def scenario():
        try:
            for call in calls:
                await command.callback(call)
        finally:
            await ctx.client.close()

    asyncio.run(scenario())


# T142-P3-A ------------------------------------------------------------------------------

def test_the_command_is_public_and_server_only(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([]))
    command = ctx.client.tree.get_command("셀프디스")
    assert command.guild_only and command.default_permissions is None and not command.parameters
    assert not getattr(command.callback, "__yoyack_gated__", False)
    asyncio.run(ctx.client.close())


def test_only_the_callers_recent_words_reach_one_call(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    ctx = context(tmp_path, monkeypatch, 45, Runner([f"  “{JAB}”  "]))
    ctx.client.message_store.upsert(MessageRecord(mid(200), 1, 2, CALLER, "다온", "!!요약좀 길게",
                                                  NOW - timedelta(minutes=1)), cached_at=NOW)
    ctx.client.message_store.upsert(MessageRecord(mid(201), 1, 2, CALLER, "다온", "8일 전 말",
                                                  NOW - timedelta(days=8)), cached_at=NOW)
    asked = interaction(ctx)
    roast(ctx, asked)
    assert posted(ctx) == [f"🪞 <@{CALLER}> {JAB}"]
    mentions = ctx.channel.send.await_args.kwargs["allowed_mentions"]
    assert not mentions.users and not mentions.everyone
    asked.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    asked.delete_original_response.assert_awaited_once()
    (prompt, rows), = ctx.runner.calls
    messages = [r for r in rows if r["type"] == "message"]
    assert [r["body"] for r in messages] == [f"대화 {n}" for n in range(2, 46, 3)]   # 15, oldest first
    assert len({r["speaker"] for r in messages}) == 1                                # nobody else
    assert prompt.startswith(self_roast.SELF_ROAST_PROMPT) and self_roast.DEFAULT_VOICE in prompt
    line = json.loads(next(r.message for r in caplog.records if '"self_roast_request"' in r.message))
    assert (line["outcome"], line["messages"], line["calls"], line["tone"]) == ("success", 15, 1, "default")
    assert "대화" not in caplog.text and "점심" not in caplog.text


def test_at_most_thirty_and_too_few(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 120, Runner([JAB]))
    roast(ctx, interaction(ctx))
    bodies = [r["body"] for r in ctx.runner.calls[0][1] if r["type"] == "message"]
    assert len(bodies) == 30 and bodies[-1] == "대화 119"
    (tmp_path / "few").mkdir()
    few = context(tmp_path / "few", monkeypatch, 5, Runner([]))
    asked = interaction(few)
    roast(few, asked)
    assert few.runner.calls == [] and posted(few) == [] and private(asked) == [self_roast.TOO_FEW]


def test_the_server_tone_sets_the_voice(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 45, Runner([JAB]))
    SQLiteToneStore(ctx.path).save(1, BY_KEY["pirate"].tone, expected_version=0)
    roast(ctx, interaction(ctx))
    prompt = ctx.runner.calls[0][0]
    assert f"«{BY_KEY['pirate'].tone}»" in prompt and self_roast.DEFAULT_VOICE not in prompt
    assert prompt.index("지킬 것:") < prompt.index("«")


# T142-P3-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("bad", "reason"), [
    ("가" * 151, "length"), ("이 병신 같은 말버릇이오.", "hate"), ("<@123> 놀리오.", "mention"),
    ("https://example.invalid 보시오.", "mention"), ("P1의 말버릇이오.", "internal"), ("   ", "empty"),
])
def test_a_bad_answer_is_retried_once_then_refused(tmp_path, monkeypatch, caplog, bad, reason) -> None:
    caplog.set_level(logging.INFO)
    assert self_roast.problem(self_roast.clean_answer(bad)) == reason
    ctx = context(tmp_path, monkeypatch, 45, Runner([bad, JAB]))
    roast(ctx, interaction(ctx))
    assert posted(ctx) == [f"🪞 <@{CALLER}> {JAB}"] and len(ctx.runner.calls) == 2
    assert self_roast.RETRY_NOTE in ctx.runner.calls[1][0] and self_roast.RETRY_NOTE not in ctx.runner.calls[0][0]
    ctx2_path = tmp_path / "again"
    ctx2_path.mkdir()
    again = context(ctx2_path, monkeypatch, 45, Runner([bad, bad]))
    asked = interaction(again)
    roast(again, asked)
    assert posted(again) == [] and private(asked) == [self_roast.FAILED]
    line = [json.loads(r.message) for r in caplog.records if '"self_roast_request"' in r.message][-1]
    assert (line["outcome"], line["rejected"], line["calls"]) == ("rejected", reason, 2)


def test_cooldown_per_person_only_after_a_post(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 45, Runner([CodexRunError(CodexFailure.TIMEOUT), JAB, JAB]))
    first, second, third = interaction(ctx), interaction(ctx), interaction(ctx)
    roast(ctx, first, second, third)
    assert private(first) == [self_roast.FAILED]                  # a failure starts no cooldown
    assert posted(ctx) == [f"🪞 <@{CALLER}> {JAB}"]
    assert private(third)[0].startswith("🧊 셀프디스는 숨 좀 돌리고 하시오. 60초 뒤에")
    assert len(ctx.runner.calls) == 2


def test_boundaries_answer_only_the_caller(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 45, Runner([]), ready=False)
    asked = interaction(ctx)
    roast(ctx, asked)
    assert private(asked) == [self_roast.NOT_READY] and posted(ctx) == [] and ctx.runner.calls == []
    path = tmp_path / "unwatched"
    path.mkdir()
    other = context(path, monkeypatch, 45, Runner([]))
    other.client.watch_store.replace(1, frozenset())
    asked = interaction(other)
    roast(other, asked)
    assert private(asked) == [self_roast.UNWATCHED] and posted(other) == []


def test_notices_are_in_the_catalog() -> None:
    for text in (self_roast.TOO_FEW, self_roast.COOLDOWN.format(seconds=42), self_roast.FAILED,
                 self_roast.NOT_READY, self_roast.UNWATCHED, self_roast.UNAVAILABLE, self_roast.QUEUE):
        assert unmatched(text) == [], text
