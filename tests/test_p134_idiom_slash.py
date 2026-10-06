"""1.3.4-P1: `/말하자면` — only the answer reaches the channel (T134-P1-A/B)."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from test_p130_idiom import FOUR, PICK, Runner, context, event

from yoyackbot import idiom
from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.state import CooldownKind
from yoyackbot.watch_store import SQLiteWatchStore


def interaction(ctx, *, guild=True):
    return SimpleNamespace(
        guild=ctx.guild if guild else None, channel=ctx.channel if guild else None, guild_id=1,
        user=SimpleNamespace(id=9), created_at=datetime.now(UTC) - timedelta(milliseconds=120),
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(), delete_original_response=AsyncMock(),
    )


def slash(ctx, *calls):
    """Run `/말하자면` through the registered command, then any extra coroutine factories."""
    command = ctx.client.tree.get_command("말하자면")

    async def scenario():
        try:
            for call in calls:
                await (command.callback(call) if isinstance(call, SimpleNamespace) else call())
        finally:
            await ctx.client.close()

    asyncio.run(scenario())


def posted(ctx):
    return [c.args[0] for c in ctx.channel.send.await_args_list]


def private(item):
    return [c.kwargs["content"] for c in item.edit_original_response.await_args_list]


# T134-P1-A ------------------------------------------------------------------------------

def test_the_command_is_public_and_server_only(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([]))
    command = ctx.client.tree.get_command("말하자면")
    assert command.guild_only and command.default_permissions is None
    assert not getattr(command.callback, "__yoyack_gated__", False)
    asyncio.run(ctx.client.close())


def test_only_the_answer_reaches_the_channel(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    ctx = context(tmp_path, monkeypatch, 45, Runner([FOUR, PICK]))
    asked = interaction(ctx)
    slash(ctx, asked)
    assert posted(ctx) == ["말하자면 우왕좌왕? 🎯"]                     # a plain channel message
    assert ctx.channel.send.await_args.kwargs["allowed_mentions"].everyone is False
    asked.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    asked.delete_original_response.assert_awaited_once()               # the private wait goes away
    asked.edit_original_response.assert_not_awaited()
    bodies = [r["body"] for r in ctx.runner.calls[0][1] if r["type"] == "message"]
    assert len(bodies) == 30 and bodies[-1] == "대화 45"
    metrics = json.loads(next(r.message for r in caplog.records if '"idiom_request"' in r.message))
    timing_line = json.loads(next(r.message for r in caplog.records if '"request_timing"' in r.message))
    assert (metrics["surface"], metrics["outcome"]) == ("slash", "success")
    assert timing_line["kind"] == "idiom" and 50 <= timing_line["discord_delay_ms"] < 5000
    assert "대화" not in caplog.text and "우왕좌왕" not in caplog.text


def test_text_and_slash_share_one_cooldown(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([FOUR, PICK]))
    later = interaction(ctx)

    async def text():
        await ctx.client.on_message(event(ctx))

    slash(ctx, text, later)
    seconds = ctx.client.settings.success_cooldown_seconds
    assert posted(ctx) == ["말하자면 우왕좌왕? 🎯"]
    assert private(later) == [idiom.cooldown_notice(seconds)]
    later.delete_original_response.assert_not_awaited()


def test_slash_success_blocks_the_text_command_too(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([FOUR, PICK]))

    async def text():
        await ctx.client.on_message(event(ctx))

    slash(ctx, interaction(ctx), text)
    seconds = ctx.client.settings.success_cooldown_seconds
    assert posted(ctx) == ["말하자면 우왕좌왕? 🎯", idiom.cooldown_notice(seconds)]


def test_a_running_summary_makes_it_busy(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([]))
    asked = interaction(ctx)

    async def occupy():
        from yoyackbot.workflow import build_workflow
        ctx.client.summary_workflow = build_workflow(ctx.client.settings, ctx.client,
                                                     ctx.client.watch_store, ctx.client.message_store)
        await ctx.client.summary_workflow.states.admit(1, 2, kind=CooldownKind.SUMMARY)

    slash(ctx, occupy, asked)
    assert posted(ctx) == [] and private(asked) == [idiom.BUSY_NOTICE] and ctx.runner.calls == []


# T134-P1-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("case", "notice"), [
    ("empty", idiom.EMPTY_NOTICE), ("not_ready", idiom.NOT_READY_NOTICE), ("limit", idiom.LIMIT_NOTICE),
    ("unwatched", idiom.UNWATCHED_NOTICE), ("revoked", idiom.INVALIDATED_NOTICE),
    ("model", idiom.FAILED_NOTICE), ("bad_answer", idiom.FAILED_NOTICE), ("no_guild", idiom.UNWATCHED_NOTICE),
])
def test_every_notice_goes_only_to_the_caller(tmp_path, monkeypatch, case, notice) -> None:
    answers = {"model": [CodexRunError(CodexFailure.TIMEOUT)], "bad_answer": ["틀림", "또 틀림"]}.get(case, [])
    ctx = context(tmp_path, monkeypatch, 0 if case == "empty" else 5, Runner(answers),
                  max_messages="20" if case == "limit" else "1000", ready=case != "not_ready")
    if case == "unwatched":
        SQLiteWatchStore(ctx.path).replace(1, frozenset())
    if case == "revoked":
        monkeypatch.setattr("yoyackbot.workflow.valid_channel", lambda *_: False)
    asked = interaction(ctx, guild=case != "no_guild")
    slash(ctx, asked)
    assert posted(ctx) == [] and private(asked) == [notice]
    asked.delete_original_response.assert_not_awaited()
    assert not list((tmp_path / "inputs").glob("request-*"))


def test_a_failed_post_tells_the_caller(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([FOUR, PICK]))
    ctx.channel.send = AsyncMock(side_effect=discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x"))
    asked = interaction(ctx)
    slash(ctx, asked)
    assert private(asked) == [idiom.FAILED_NOTICE]

    async def status():
        return await ctx.client.summary_workflow.states.admit(1, 2, kind=CooldownKind.IDIOM)

    assert asyncio.run(status()).kind.value == "accepted"  # no cooldown after a failed post


def test_a_lost_private_reply_does_not_break_the_answer(tmp_path, monkeypatch, caplog) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([FOUR, PICK]))
    asked = interaction(ctx)
    asked.delete_original_response = AsyncMock(side_effect=discord.HTTPException(
        SimpleNamespace(status=404, reason="x"), "x"))
    slash(ctx, asked)
    assert posted(ctx) == ["말하자면 우왕좌왕? 🎯"] and "idiom_slash_cleanup_failed" in caplog.text


def test_the_text_command_keeps_its_channel_notices(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    ctx = context(tmp_path, monkeypatch, 0, Runner([]))

    async def text():
        await ctx.client.on_message(event(ctx))

    slash(ctx, text)
    assert posted(ctx) == [idiom.EMPTY_NOTICE]
    metrics = json.loads(next(r.message for r in caplog.records if '"idiom_request"' in r.message))
    assert metrics["surface"] == "text"
