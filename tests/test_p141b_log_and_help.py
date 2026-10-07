"""1.4.1b-P1: the user's 처형 log layout and `/처형도움` (T141b-P1-A/B)."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from test_p140_audit_log import MOD, NOW, TARGET, client_with, entry
from test_p140_tone_notices import NoticeEngine, table_for, toned, toned_client

from yoyackbot.execution_log import GAP, RULE, log_message, timeout_event
from yoyackbot.notices import BOOK, CATALOG, localize, render, unmatched
from yoyackbot.parser import EXECUTION_HELP

APPLIED = f"""{RULE}
⚔️처형했소

☠️<@{TARGET}> 을(를) 🗡️<@{MOD}> 이(가) 처형하였소.

📜사유는 "야식 금지 위반" 이며, ⏳10분 동안 시체요.

🕑2026-10-07 21:10 이후에 오시오🚨
{RULE}
{GAP}"""

RELEASED = f"""{RULE}
🕊️ 사면되었소

☠️<@{TARGET}> 을(를) 🗡️<@{MOD}> 이(가) 사면하였소

📜사유는 "시험이었소" 이였소.

🗽자유를 만끽하시오!⛓️‍💥
{RULE}
{GAP}"""


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


# T141b-P1-A ------------------------------------------------------------------------------

def test_the_logs_match_the_requested_layout_exactly() -> None:
    applied = timeout_event(entry(None, NOW + timedelta(minutes=10), reason="야식\n금지   위반"))
    assert log_message(applied, MOD) == APPLIED
    released = timeout_event(entry(NOW + timedelta(minutes=3), None, reason="시험이었소"))
    assert log_message(released, MOD) == RELEASED
    assert RULE == "-" * 54 and GAP == "\u200b"


def test_extension_unknown_executor_no_reason_and_time_zone() -> None:
    extended = timeout_event(entry(NOW + timedelta(minutes=1), NOW + timedelta(hours=2), reason=None))
    text = log_message(extended, None)
    assert "\n⚔️처형을 연장했소\n\n" in text
    assert f"☠️<@{TARGET}> 을(를) 🗡️알 수 없는 사람 이(가) 처형을 연장하였소." in text
    assert '📜사유는 "사유 없음" 이며, ⏳2시간 동안 시체요.' in text
    assert "🕑2026-10-07 21:00 이후에 오시오🚨" in log_message(timeout_event(entry(
        None, datetime(2026, 10, 7, 12, tzinfo=UTC), reason=None)), MOD)
    utc = log_message(timeout_event(entry(None, NOW + timedelta(minutes=10))), MOD, ZoneInfo("UTC"))
    assert "🕑2026-10-07 12:10 이후에 오시오🚨" in utc


def test_the_posted_log_keeps_the_frame_and_pings_nobody(tmp_path, monkeypatch) -> None:
    client, home, log_channel = client_with(tmp_path, monkeypatch)

    async def scenario():
        try:
            await client.on_audit_log_entry_create(entry(None, NOW + timedelta(minutes=10), guild=home,
                                                         reason="야식 금지 위반"))
        finally:
            await client.close()

    asyncio.run(scenario())
    posted = log_channel.send.await_args
    assert posted.args[0] == APPLIED
    mentions = posted.kwargs["allowed_mentions"]
    assert not mentions.users and not mentions.roles and not mentions.everyone


# T141b-P1-B ------------------------------------------------------------------------------

def test_execution_help_command(tmp_path, monkeypatch) -> None:
    client, _home, _channel = client_with(tmp_path, monkeypatch)
    command = client.tree.get_command("처형도움")
    assert command.guild_only and command.default_permissions is None and not command.parameters
    asked = SimpleNamespace(guild_id=1, response=SimpleNamespace(send_message=AsyncMock()))
    asyncio.run(command.callback(asked))
    sent = asked.response.send_message.await_args
    assert sent.args[0] == EXECUTION_HELP and sent.kwargs["ephemeral"] is True
    for phrase in ("`/처형 대상 [시간] [사유]`", "`/사면 대상 [사유]`", "`/처형설정 채널관리`",
                   "`/처형설정 관리역할`", "기본 30초, 최대 28일", "`내맴`", "400자", "서버 관리자만",
                   "자기와 같거나 높은 역할", "로그 채널을 정해야"):
        assert phrase in EXECUTION_HELP, phrase
    assert len(EXECUTION_HELP) < 2000
    asyncio.run(client.close())


def test_new_lines_are_rewritable_and_the_frame_stays() -> None:
    for text in (APPLIED, RELEASED, EXECUTION_HELP):
        assert [line for line in unmatched(text) if line not in (RULE, GAP, "")] == [], text
    BOOK.set(1, table_for())
    shown = localize(1, APPLIED)
    lines = shown.split("\n")
    assert lines[0] == lines[-2] == RULE and lines[-1] == GAP
    assert lines[1] == toned("⚔️처형했소") and lines[3] == toned(CATALOG["execution_log.applied"].text) \
        .replace("{target}", f"<@{TARGET}>").replace("{executor}", f"<@{MOD}>")
    assert "야식 금지 위반" in shown and "10분" in shown
    assert localize(1, EXECUTION_HELP) == toned(EXECUTION_HELP)
    assert localize(2, APPLIED) == APPLIED


def test_old_log_rewrites_are_never_reused(tmp_path, monkeypatch) -> None:
    """A server's 1.4.0 rewrites live under keys this release no longer has (or whose text no
    longer fits); only the new lines are written once after start."""
    for key in ("execution_log.apply", "execution_log.extend", "execution_log.release",
                "execution_log.until", "execution_log.reason"):
        assert key not in CATALOG
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    version = tones.save(1, "보고서체", expected_version=0)
    old = {key: text for key, text in table_for().items()
           if not key.startswith("execution_log.") and key != "execution_help"}
    old["execution_log.apply"] = "⚔️ 처형자 {executor} → {target}"            # a 1.4.0 key
    client.notices.replace(1, version, old)
    monkeypatch.setattr(type(client), "guilds", property(lambda self: [SimpleNamespace(id=1)]))

    async def scenario():
        try:
            BOOK.load(await asyncio.to_thread(client.notices.current))
            assert "execution_log.apply" not in BOOK.table(1)
            await client._catch_up_notices()
        finally:
            await client.close()

    asyncio.run(scenario())
    asked = {line["key"] for _, lines in engine.calls for line in lines if line["type"] == "notice"}
    assert asked == {key for key in CATALOG if key.startswith("execution_log.")} | {"execution_help"}
    assert set(BOOK.table(1)) == set(CATALOG)
    assert render(APPLIED, BOOK.table(1)).split("\n")[1] == toned("⚔️처형했소")
