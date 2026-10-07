"""1.4.1-P1: `/사면 대상 사유` lifts a timeout with `/처형`'s people and hierarchy (T141-P1-A/B)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from test_p140_audit_log import client_with, entry
from test_p140_execute_command import BOT, CALLER, EXEC_ROLE, OWNER, TARGET, ask, member, world
from test_p140_tone_notices import NoticeEngine, table_for, toned, toned_client

from yoyackbot.channel_config import SLASH_PERMISSIONS
from yoyackbot.execute_command import (
    LONG_REASON,
    NOT_TIMED_OUT,
    PARDON_BOT,
    PARDON_BOT_CANNOT,
    PARDON_FAILED,
    PARDON_HIGHER,
    PARDON_NOT_ALLOWED,
    PARDON_PROTECTED,
    PARDON_SELF,
    run_pardon,
    timed_out,
)
from yoyackbot.notice_writer import SQLiteNoticeStore
from yoyackbot.notices import BOOK, CATALOG, localize, unmatched
from yoyackbot.tone import SQLiteToneStore
from yoyackbot.watch_store import SQLiteWatchStore


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


def jailed(member_id, *, minutes=10, **kwargs):
    person = member(member_id, **kwargs)
    person.timed_out_until = datetime.now(UTC) + timedelta(minutes=minutes) if minutes else None
    return person


def pardon(store, home, target, reason=None, caller_id=CALLER, remember=None):
    asked = ask(home, caller_id)
    calls = []
    outcome = asyncio.run(run_pardon(asked, target, reason, store=store,
                                     remember=remember or (lambda *a: calls.append(a))))
    answer = asked.followup.send.await_args.args[0] if asked.followup.send.await_args else None
    return outcome, answer, calls, asked


# T141-P1-A ------------------------------------------------------------------------------

def test_pardon_lifts_the_timeout_with_the_default_reason(tmp_path) -> None:
    store, home, _ = world(tmp_path)
    target = jailed(TARGET, position=5)
    order = []
    target.timeout = AsyncMock(side_effect=lambda *a, **k: order.append("timeout"))
    outcome, answer, _calls, asked = pardon(store, home, target,
                                            remember=lambda *a: order.append(("remember", a)))
    assert outcome == "success" and order == [("remember", (1, TARGET, CALLER)), "timeout"]
    target.timeout.assert_awaited_once_with(None, reason="내맴")
    asked.response.defer.assert_awaited_once_with(ephemeral=True)
    assert answer == f"🕊️ <@{TARGET}>의 처형을 풀었소. 📝 사유: 내맴"
    assert asked.followup.send.await_args.kwargs["ephemeral"] is True
    assert pardon(store, home, jailed(TARGET, position=5), "  잘못\n봤소 ")[1].endswith("사유: 잘못 봤소")


@pytest.mark.parametrize(("caller", "allowed"), [
    (member(CALLER, position=10, roles=(EXEC_ROLE,)), True),
    (member(CALLER, position=10, admin=True), True),
    (member(CALLER, position=10, roles=(71,)), False),
    (member(CALLER, position=10), False),
])
def test_the_same_people_as_execution(tmp_path, caller, allowed) -> None:
    store, home, _ = world(tmp_path, caller=caller)
    target = jailed(TARGET, position=5)
    outcome, answer, *_ = pardon(store, home, target)
    assert (outcome == "success") is allowed
    if not allowed:
        assert answer == PARDON_NOT_ALLOWED and not target.timeout.await_count


def test_the_owner_may_pardon_higher_roles(tmp_path) -> None:
    store, home, people = world(tmp_path)
    people[OWNER] = member(OWNER, position=1)
    assert pardon(store, home, jailed(TARGET, position=40), caller_id=OWNER)[0] == "success"


@pytest.mark.parametrize(("target", "me", "message", "outcome"), [
    (jailed(CALLER, position=5), None, PARDON_SELF, "refused"),
    (jailed(TARGET, position=5, bot=True), None, PARDON_BOT, "refused"),
    (jailed(OWNER, position=1), None, PARDON_PROTECTED, "refused"),
    (jailed(TARGET, position=1, admin=True), None, PARDON_PROTECTED, "refused"),
    (jailed(TARGET, position=10), None, PARDON_HIGHER, "refused"),          # same height
    (jailed(TARGET, position=20), None, PARDON_HIGHER, "refused"),
    (jailed(TARGET, position=5), member(BOT, position=50, moderate=False), PARDON_BOT_CANNOT, "refused"),
    (jailed(TARGET, position=5), member(BOT, position=5, moderate=True), PARDON_BOT_CANNOT, "refused"),
    (jailed(TARGET, position=5, minutes=None), None, NOT_TIMED_OUT, "not_timed_out"),
    (jailed(TARGET, position=5, minutes=-1), None, NOT_TIMED_OUT, "not_timed_out"),   # already over
])
def test_refusals_never_reach_discord(tmp_path, target, me, message, outcome) -> None:
    store, home, _ = world(tmp_path, me=me)
    got, answer, calls, _ = pardon(store, home, target)
    assert (got, answer) == (outcome, message) and calls == [] and not target.timeout.await_count


def test_long_reason_and_discord_errors(tmp_path) -> None:
    store, home, _ = world(tmp_path)
    target = jailed(TARGET, position=5)
    assert pardon(store, home, target, "가" * 401)[:2] == ("long_reason", LONG_REASON)
    assert not target.timeout.await_count
    for error, message, outcome in (
        (discord.Forbidden(SimpleNamespace(status=403, reason="x"), "x"), PARDON_BOT_CANNOT, "forbidden"),
        (discord.HTTPException(SimpleNamespace(status=500, reason="x"), "x"), PARDON_FAILED, "failed"),
    ):
        target.timeout = AsyncMock(side_effect=error)
        assert pardon(store, home, target)[:2] == (outcome, message)


def test_timed_out_reads_the_end_time() -> None:
    now = datetime(2026, 10, 7, tzinfo=UTC)
    assert timed_out(SimpleNamespace(timed_out_until=now + timedelta(seconds=1)), now)
    assert not timed_out(SimpleNamespace(timed_out_until=now), now)
    assert not timed_out(SimpleNamespace(), now)


def test_the_command_is_registered(tmp_path, monkeypatch) -> None:
    client, _home, _channel = client_with(tmp_path, monkeypatch)
    command = client.tree.get_command("사면")
    assert command.guild_only and command.default_permissions == SLASH_PERMISSIONS
    assert [p.name for p in command.parameters] == ["대상", "사유"]
    assert [p.required for p in command.parameters] == [True, False]
    assert command.callback.__yoyack_gated__ and client.tree.get_command("처형") is not None
    asyncio.run(client.close())


# T141-P1-B ------------------------------------------------------------------------------

def test_the_release_log_names_the_pardoner(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    client.executions.set_roles(1, [EXEC_ROLE])
    home.owner_id, home.me = OWNER, member(BOT, position=50, moderate=True)
    home.fetch_member = AsyncMock(return_value=member(CALLER, position=10, roles=(EXEC_ROLE,)))
    target = jailed(TARGET, position=5)

    async def scenario():
        try:
            assert await run_pardon(ask(home), target, "비밀 사유", store=client.executions,
                                    remember=client.remember_execution) == "success"
            lifted = entry(datetime.now(UTC) + timedelta(minutes=5), None, guild=home, user_id=BOT,
                           reason="비밀 사유")
            await client.on_audit_log_entry_create(lifted)
            await client.on_audit_log_entry_create(lifted)      # credited once only
        finally:
            await client.close()

    asyncio.run(scenario())
    first, second = (call.args[0] for call in log_channel.send.await_args_list)
    assert f"\n☠️<@{TARGET}> 을(를) 🗡️<@{CALLER}> 이(가) 사면하였소\n" in first
    assert f"🗡️<@{BOT}> 이(가)" in second
    assert "execution_logged kind=release by_command=True" in caplog.text
    assert "비밀 사유" not in caplog.text


def test_pardon_notices_are_in_the_catalog_and_follow_the_server() -> None:
    texts = [PARDON_NOT_ALLOWED, PARDON_SELF, PARDON_BOT, PARDON_PROTECTED, PARDON_HIGHER,
             PARDON_BOT_CANNOT, NOT_TIMED_OUT, PARDON_FAILED,
             f"🕊️ <@{TARGET}>의 처형을 풀었소. 📝 사유: 내맴"]
    for text in texts:
        assert unmatched(text) == [], text
    BOOK.set(1, table_for())
    assert localize(1, NOT_TIMED_OUT) == toned(NOT_TIMED_OUT)
    assert localize(1, texts[-1]) == f"🕊️ <@{TARGET}>의 처형을 풀었소. 📝 사유: ~습니다 내맴"
    assert localize(2, NOT_TIMED_OUT) == NOT_TIMED_OUT


def test_only_the_missing_notices_are_written_and_added(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    tone = "점잖은 보고서체로 쓰시오."
    version = tones.save(1, tone, expected_version=0)
    older = {key: text for key, text in table_for().items() if not key.startswith("pardon.")}
    older["summary.busy"] = "⏳ 예전에 쓴 문구"
    client.notices.replace(1, version, older)
    monkeypatch.setattr(type(client), "guilds", property(lambda self: [SimpleNamespace(id=1)]))

    async def scenario():
        try:
            BOOK.load(await asyncio.to_thread(client.notices.current))
            await client._catch_up_notices()
        finally:
            await client.close()

    asyncio.run(scenario())
    asked = {line["key"] for _, lines in engine.calls for line in lines if line["type"] == "notice"}
    pardon_keys = {key for key in CATALOG if key.startswith("pardon.")}
    assert asked == pardon_keys                                   # nothing else is rewritten
    stored = client.notices.current()[1]
    assert stored["summary.busy"] == "⏳ 예전에 쓴 문구" and set(stored) == set(CATALOG)
    assert BOOK.table(1) == stored
    assert f"written={len(pardon_keys)} kept=0" in caplog.text and "added=True" in caplog.text
    assert client.notices.pending() == []


def test_adding_to_an_old_tone_version_is_refused(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path)
    tones, store = SQLiteToneStore(path), SQLiteNoticeStore(path)
    first = tones.save(1, "가", expected_version=0)
    store.replace(1, first, {"summary.busy": toned(CATALOG["summary.busy"].text)})
    second = tones.save(1, "나", expected_version=first)
    assert store.add(1, first, {"pardon.self": toned(CATALOG["pardon.self"].text)}) is False
    assert store.add(1, second, {"pardon.self": toned(CATALOG["pardon.self"].text)}) is True
    assert store.current() == {1: {"pardon.self": toned(CATALOG["pardon.self"].text)}}   # old rows go
