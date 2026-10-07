"""1.4.1c-P1: `/처형` leaves "☠️" and `/사면` "🕊️" in the command's channel (T141c-P1-A/B)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from test_p140_execute_command import CALLER, TARGET, ask, member, world
from test_p141_pardon import jailed

from yoyackbot.execute_command import (
    EXECUTE_MARK,
    PARDON_MARK,
    run_execution,
    run_pardon,
)


def with_channel(home, channel, caller_id=CALLER):
    asked = ask(home, caller_id)
    asked.channel = channel
    order = []
    asked.followup.send = AsyncMock(side_effect=lambda *a, **k: order.append("answer"))
    if channel is not None:
        channel.send = AsyncMock(side_effect=channel.send.side_effect
                                 or (lambda *a, **k: order.append("mark")))
    return asked, order


def execute(store, home, target, channel, **kwargs):
    asked, order = with_channel(home, channel, **kwargs)
    outcome = asyncio.run(run_execution(asked, target, None, None, store=store, remember=lambda *a: None))
    return outcome, order, asked


def pardon(store, home, target, channel, **kwargs):
    asked, order = with_channel(home, channel, **kwargs)
    outcome = asyncio.run(run_pardon(asked, target, None, store=store, remember=lambda *a: None))
    return outcome, order, asked


def channel(side_effect=None):
    return SimpleNamespace(send=AsyncMock(side_effect=side_effect))


# T141c-P1-A ------------------------------------------------------------------------------

def test_success_marks_the_channel_after_the_answer(tmp_path) -> None:
    store, home, _ = world(tmp_path)
    room = channel()
    outcome, order, _ = execute(store, home, member(TARGET, position=5), room)
    assert outcome == "success" and order == ["answer", "mark"]
    room.send.assert_awaited_once()
    assert room.send.await_args.args == (EXECUTE_MARK,) == ("☠️",)
    mentions = room.send.await_args.kwargs["allowed_mentions"]
    assert not mentions.users and not mentions.roles and not mentions.everyone

    room = channel()
    outcome, order, _ = pardon(store, home, jailed(TARGET, position=5), room)
    assert outcome == "success" and order == ["answer", "mark"]
    assert room.send.await_args.args == (PARDON_MARK,) == ("🕊️",)


@pytest.mark.parametrize("case", ["refused", "not_allowed", "discord_error", "not_timed_out"])
def test_no_mark_without_success(tmp_path, case) -> None:
    caller = member(CALLER, position=10) if case == "not_allowed" else None
    store, home, _ = world(tmp_path, caller=caller)
    room = channel()
    if case == "not_timed_out":
        outcome, *_ = pardon(store, home, jailed(TARGET, position=5, minutes=None), room)
    else:
        target = member(CALLER if case == "refused" else TARGET, position=5)
        if case == "discord_error":
            target.timeout = AsyncMock(side_effect=discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x"))
        outcome, *_ = execute(store, home, target, room)
    assert outcome != "success" and not room.send.await_count


# T141c-P1-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("room", "event"), [
    (None, "execution_mark_unavailable"),
    (SimpleNamespace(), "execution_mark_unavailable"),                     # cannot send there
    (channel(discord.Forbidden(SimpleNamespace(status=403, reason="x"), "x")), "execution_mark_failed"),
    (channel(OSError("network")), "execution_mark_failed"),
])
def test_a_lost_mark_never_changes_the_result(tmp_path, caplog, room, event) -> None:
    caplog.set_level(logging.INFO)
    store, home, _ = world(tmp_path)
    asked = ask(home)
    asked.channel = room
    target = member(TARGET, position=5)
    outcome = asyncio.run(run_execution(asked, target, "10분", "비밀 사유", store=store,
                                        remember=lambda *a: None))
    assert outcome == "success" and target.timeout.await_count == 1
    assert asked.followup.send.await_args.args[0].startswith("⚔️ <@")
    assert event in caplog.text and "비밀 사유" not in caplog.text
