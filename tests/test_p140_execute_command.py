"""1.4.0-P3: `/처형 대상 시간 사유` with its permission and hierarchy checks (T140-P3-A/B)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from test_p140_audit_log import client_with, entry

from yoyackbot.channel_config import SLASH_PERMISSIONS
from yoyackbot.execute_command import (
    BAD_TIME,
    BOT_CANNOT,
    BOT_TARGET,
    FAILED,
    HIGHER,
    LONG_REASON,
    NOT_ALLOWED,
    PROTECTED,
    SELF,
    DurationError,
    parse_duration,
    run_execution,
)
from yoyackbot.execution import SQLiteExecutionStore
from yoyackbot.watch_store import SQLiteWatchStore

EXEC_ROLE, OWNER, BOT, CALLER, TARGET = 70, 1, 900, 503, 502


def member(member_id, *, position=1, roles=(), admin=False, bot=False, moderate=False):
    return SimpleNamespace(
        id=member_id, bot=bot, roles=[SimpleNamespace(id=r) for r in roles],
        top_role=SimpleNamespace(position=position),
        guild_permissions=SimpleNamespace(administrator=admin, moderate_members=moderate),
        timeout=AsyncMock(), mention=f"<@{member_id}>",
    )


def world(tmp_path, *, caller=None, me=None):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path)
    store = SQLiteExecutionStore(path)
    store.set_roles(1, [EXEC_ROLE])
    people = {CALLER: caller or member(CALLER, position=10, roles=(EXEC_ROLE,))}
    home = SimpleNamespace(id=1, owner_id=OWNER, me=me or member(BOT, position=50, moderate=True),
                           fetch_member=AsyncMock(side_effect=lambda uid: people[uid]))
    return store, home, people


def ask(home, caller_id=CALLER):
    return SimpleNamespace(guild=home, user=SimpleNamespace(id=caller_id),
                           response=SimpleNamespace(defer=AsyncMock()),
                           followup=SimpleNamespace(send=AsyncMock()))


def execute(store, home, target, time_text=None, reason=None, caller_id=CALLER, remember=None):
    asked = ask(home, caller_id)
    calls = []

    def note(*args):
        calls.append(("remember", args))

    outcome = asyncio.run(run_execution(asked, target, time_text, reason, store=store,
                                        remember=remember or note))
    answer = asked.followup.send.await_args.args[0] if asked.followup.send.await_args else None
    return outcome, answer, calls, asked


# T140-P3-A ------------------------------------------------------------------------------

def test_defaults_time_out_for_thirty_seconds_with_the_default_reason(tmp_path) -> None:
    store, home, _people = world(tmp_path)
    target = member(TARGET, position=5)
    order = []
    target.timeout = AsyncMock(side_effect=lambda *a, **k: order.append("timeout"))
    outcome, answer, _calls, asked = execute(store, home, target, remember=lambda *a: order.append(("remember", a)))
    assert outcome == "success" and order == [("remember", (1, TARGET, CALLER)), "timeout"]
    target.timeout.assert_awaited_once_with(timedelta(seconds=30), reason="내맴")
    asked.response.defer.assert_awaited_once_with(ephemeral=True)
    assert answer == f"⚔️ <@{TARGET}>을(를) 30초 동안 처형했소. 📝 사유: 내맴"
    assert asked.followup.send.await_args.kwargs["ephemeral"] is True


@pytest.mark.parametrize(("text", "seconds"), [
    (None, 30), ("", 30), ("30", 30), ("30초", 30), ("10분", 600), ("10 분", 600), ("2시간", 7200),
    ("1일", 86400), ("28일", 28 * 86400),
])
def test_duration_formats(text, seconds) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["0", "29일", "1.5시간", "-3", "십분", "10분 30초", "3주"])
def test_bad_durations(text) -> None:
    with pytest.raises(DurationError):
        parse_duration(text)


def test_custom_time_and_reason(tmp_path) -> None:
    store, home, _ = world(tmp_path)
    target = member(TARGET, position=5)
    outcome, answer, *_ = execute(store, home, target, "2시간", "  도배\n그만  ")
    target.timeout.assert_awaited_once_with(timedelta(hours=2), reason="도배 그만")
    assert outcome == "success" and "2시간 동안" in answer


@pytest.mark.parametrize(("caller", "allowed"), [
    (member(CALLER, position=10, roles=(EXEC_ROLE,)), True),
    (member(CALLER, position=10, admin=True), True),
    (member(CALLER, position=10, roles=(71,)), False),
    (member(CALLER, position=10), False),
])
def test_who_may_execute(tmp_path, caller, allowed) -> None:
    store, home, _ = world(tmp_path, caller=caller)
    target = member(TARGET, position=5)
    outcome, answer, *_ = execute(store, home, target)
    assert (outcome == "success") is allowed
    if not allowed:
        assert answer == NOT_ALLOWED and not target.timeout.await_count


def test_the_owner_may_execute_even_higher_roles(tmp_path) -> None:
    store, home, people = world(tmp_path)
    people[OWNER] = member(OWNER, position=1)
    target = member(TARGET, position=40)
    outcome, *_ = execute(store, home, target, caller_id=OWNER)
    assert outcome == "success"


def test_a_vanished_caller_is_refused(tmp_path) -> None:
    store, home, _ = world(tmp_path)
    home.fetch_member = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="x"), "x"))
    outcome, answer, *_ = execute(store, home, member(TARGET, position=5))
    assert (outcome, answer) == ("not_allowed", NOT_ALLOWED)


def test_the_command_is_registered(tmp_path, monkeypatch) -> None:
    client, _home, _channel = client_with(tmp_path, monkeypatch)
    command = client.tree.get_command("처형")
    assert command.guild_only and command.default_permissions == SLASH_PERMISSIONS
    assert [p.name for p in command.parameters] == ["대상", "시간", "사유"]
    assert [p.required for p in command.parameters] == [True, False, False]
    asyncio.run(client.close())


# T140-P3-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("target", "me", "message"), [
    (member(CALLER, position=5), None, SELF),
    (member(TARGET, position=5, bot=True), None, BOT_TARGET),
    (member(OWNER, position=1), None, PROTECTED),
    (member(TARGET, position=1, admin=True), None, PROTECTED),
    (member(TARGET, position=10), None, HIGHER),                    # same height as the caller
    (member(TARGET, position=20), None, HIGHER),
    (member(TARGET, position=5), member(BOT, position=50, moderate=False), BOT_CANNOT),
    (member(TARGET, position=5), member(BOT, position=5, moderate=True), BOT_CANNOT),
])
def test_refusals(tmp_path, target, me, message) -> None:
    store, home, _ = world(tmp_path, me=me)
    outcome, answer, calls, _ = execute(store, home, target)
    assert (outcome, answer) == ("refused", message) and calls == [] and not target.timeout.await_count


@pytest.mark.parametrize(("error", "message", "outcome"), [
    (discord.Forbidden(SimpleNamespace(status=403, reason="x"), "x"), BOT_CANNOT, "forbidden"),
    (discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x"), FAILED, "failed"),
])
def test_discord_errors(tmp_path, error, message, outcome) -> None:
    store, home, _ = world(tmp_path)
    target = member(TARGET, position=5)
    target.timeout = AsyncMock(side_effect=error)
    assert execute(store, home, target)[:2] == (outcome, message)


def test_bad_inputs_never_reach_discord(tmp_path) -> None:
    store, home, _ = world(tmp_path)
    target = member(TARGET, position=5)
    assert execute(store, home, target, "1.5시간")[:2] == ("bad_time", BAD_TIME)
    assert execute(store, home, target, None, "가" * 401)[:2] == ("long_reason", LONG_REASON)
    assert not target.timeout.await_count


def test_command_to_log_channel_names_the_caller(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    client.executions.set_roles(1, [EXEC_ROLE])
    caller = member(CALLER, position=10, roles=(EXEC_ROLE,))
    home.owner_id, home.me = OWNER, member(BOT, position=50, moderate=True)
    home.fetch_member = AsyncMock(return_value=caller)
    target = member(TARGET, position=5)

    async def scenario():
        try:
            outcome = await run_execution(ask(home), target, "10분", "비밀 사유", store=client.executions,
                                          remember=client.remember_execution)
            assert outcome == "success"
            now = datetime.now(UTC)
            item = entry(None, now + timedelta(minutes=10), guild=home, user_id=BOT, reason="비밀 사유")
            item.created_at = now
            await client.on_audit_log_entry_create(item)
        finally:
            await client.close()

    asyncio.run(scenario())
    posted = log_channel.send.await_args.args[0]
    assert f"처형자 <@{CALLER}> → 처형인 <@{TARGET}>" in posted and "10분" in posted
    assert "비밀 사유" not in caplog.text
