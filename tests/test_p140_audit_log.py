"""1.4.0-P2: timeouts from the audit log go to the 처형 log channel (T140-P2-A/B)."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from test_role_config import guild as fake_guild

from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient, required_intents
from yoyackbot.execution_config import AUDIT_WARNING, channel_message
from yoyackbot.execution_log import (
    NO_REASON,
    duration_text,
    log_message,
    reason_text,
    timeout_event,
)
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
BOT, MOD, TARGET, CALLER = 900, 501, 502, 503


def entry(before, after, *, user_id=MOD, reason="도배", action=discord.AuditLogAction.member_update,
          changed=True, guild=None):
    after_ns = SimpleNamespace(timed_out_until=after) if changed else SimpleNamespace(nick="새 별명")
    before_ns = SimpleNamespace(timed_out_until=before) if changed else SimpleNamespace(nick="옛 별명")
    return SimpleNamespace(action=action, before=before_ns, after=after_ns, _target_id=TARGET, user_id=user_id,
                           reason=reason, created_at=NOW, guild=guild)


# T140-P2-A ------------------------------------------------------------------------------

@pytest.mark.parametrize(("before", "after", "kind"), [
    (None, NOW + timedelta(seconds=30), "apply"),
    (NOW - timedelta(minutes=5), NOW + timedelta(minutes=10), "apply"),   # the old one had ended
    (NOW + timedelta(minutes=1), NOW + timedelta(hours=1), "extend"),
    (NOW + timedelta(minutes=1), None, "release"),
])
def test_timeout_changes_are_classified(before, after, kind) -> None:
    event = timeout_event(entry(before, after))
    assert event.kind == kind and event.target_id == TARGET and event.executor_id == MOD


@pytest.mark.parametrize("item", [
    entry(None, None), entry(None, None, changed=False),
    entry(None, NOW + timedelta(seconds=30), action=discord.AuditLogAction.kick),
])
def test_other_entries_are_ignored(item) -> None:
    assert timeout_event(item) is None


def test_message_formats() -> None:
    applied = log_message(timeout_event(entry(None, NOW + timedelta(seconds=30))), MOD)
    rule = "-" * 54
    # 1.4.1b layout; NOW is 12:00 UTC, so the end is shown as 21:00 KST
    assert applied == (f"{rule}\n⚔️처형했소\n\n☠️<@{TARGET}> 을(를) 🗡️<@{MOD}> 이(가) 처형하였소.\n\n"
                       '📜사유는 "도배" 이며, ⏳30초 동안 시체요.\n\n'
                       f"🕑2026-10-07 21:00 이후에 오시오🚨\n{rule}\n\u200b")
    extended = log_message(timeout_event(entry(NOW + timedelta(minutes=1), NOW + timedelta(hours=1, minutes=30))), MOD)
    assert "\n⚔️처형을 연장했소\n" in extended and "⏳1시간 30분 동안" in extended
    assert "이(가) 처형을 연장하였소." in extended
    released = log_message(timeout_event(entry(NOW + timedelta(minutes=1), None, reason=None)), MOD)
    assert released == (f"{rule}\n🕊️ 사면되었소\n\n☠️<@{TARGET}> 을(를) 🗡️<@{MOD}> 이(가) 사면하였소\n\n"
                        f'📜사유는 "{NO_REASON}" 이였소.\n\n🗽자유를 만끽하시오!⛓️‍💥\n{rule}\n\u200b')
    assert log_message(timeout_event(entry(None, NOW + timedelta(days=28))), None).count("알 수 없는 사람") == 1
    assert duration_text(timedelta(days=2, hours=3, minutes=4)) == "2일 3시간"
    assert reason_text("  줄\n바꿈  ") == "줄 바꿈" and reason_text("가" * 500).endswith("…")


def client_with(tmp_path, monkeypatch, *, channel=10):
    path = tmp_path / "db.sqlite"
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_DB_PATH": str(path)})
    client = YoYackClient(watch_store=SQLiteWatchStore(path), message_store=SQLiteMessageStore(path),
                          settings=settings)
    if channel:
        client.executions.set_log_channel(1, channel)
    log_channel = SimpleNamespace(id=10, send=AsyncMock())
    home = SimpleNamespace(id=1, get_channel=lambda cid: log_channel if cid == 10 else None)
    monkeypatch.setattr("yoyackbot.discord.valid_channel", lambda *_: True)
    monkeypatch.setattr(YoYackClient, "user", property(lambda self: SimpleNamespace(id=BOT)))
    return client, home, log_channel


def run(client, *coros):
    async def scenario():
        try:
            for make in coros:
                await make()
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_timeout_is_posted_without_pings(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    item = entry(None, NOW + timedelta(seconds=30), guild=home, reason="비밀 사유")
    run(client, lambda: client.on_audit_log_entry_create(item))
    text = log_channel.send.await_args.args[0]
    assert f"🗡️<@{MOD}> 이(가) 처형하였소." in text and text.endswith("\n\u200b")
    mentions = log_channel.send.await_args.kwargs["allowed_mentions"]
    assert not mentions.users and not mentions.roles and not mentions.everyone
    assert "execution_logged kind=apply by_command=False" in caplog.text and "비밀 사유" not in caplog.text


def test_no_log_channel_means_no_post(tmp_path, monkeypatch) -> None:
    client, home, log_channel = client_with(tmp_path, monkeypatch, channel=None)
    run(client, lambda: client.on_audit_log_entry_create(entry(None, NOW + timedelta(seconds=30), guild=home)))
    log_channel.send.assert_not_awaited()


# T140-P2-B ------------------------------------------------------------------------------

def test_the_bots_own_timeout_names_the_command_caller_once(tmp_path, monkeypatch) -> None:
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    by_bot = entry(None, NOW + timedelta(seconds=30), guild=home, user_id=BOT, reason="내맴")
    client.remember_execution(1, TARGET, CALLER)
    run(client, lambda: client.on_audit_log_entry_create(by_bot), lambda: client.on_audit_log_entry_create(by_bot))
    first, second = (call.args[0] for call in log_channel.send.await_args_list)
    assert f"🗡️<@{CALLER}> 이(가)" in first and f"🗡️<@{BOT}> 이(가)" in second   # matched once only


def test_a_stale_caller_is_not_used(tmp_path, monkeypatch) -> None:
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    client.remember_execution(1, TARGET, CALLER)
    client._execution_callers[1, TARGET] = (CALLER, 0.0)  # expired
    run(client, lambda: client.on_audit_log_entry_create(
        entry(None, NOW + timedelta(seconds=30), guild=home, user_id=BOT)))
    assert f"🗡️<@{BOT}> 이(가)" in log_channel.send.await_args.args[0]


@pytest.mark.parametrize("problem", ["invalid", "send_fails", "unreadable"])
def test_problems_only_warn(tmp_path, monkeypatch, caplog, problem) -> None:
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    if problem == "invalid":
        monkeypatch.setattr("yoyackbot.discord.valid_channel", lambda *_: False)
    if problem == "send_fails":
        log_channel.send.side_effect = discord.HTTPException(SimpleNamespace(status=403, reason="x"), "x")
    if problem == "unreadable":
        def broken(_guild_id):
            raise OSError("locked")
        client.executions.log_channel = broken
    run(client, lambda: client.on_audit_log_entry_create(entry(None, NOW + timedelta(seconds=30), guild=home)))
    expected = {"invalid": "execution_log_channel_unavailable", "send_fails": "execution_log_post_failed",
                "unreadable": "execution_log_settings_unreadable"}[problem]
    assert expected in caplog.text


def test_intent_and_missing_audit_permission_warning() -> None:
    assert required_intents().moderation
    home = fake_guild()
    home.me = SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=False))
    assert AUDIT_WARNING in channel_message(home, None)
    home.me = SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=True))
    assert AUDIT_WARNING not in channel_message(home, 10)
