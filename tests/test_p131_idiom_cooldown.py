"""1.3.1-P1: `!!말하자면` answers without a start notice and keeps its own cooldown (T131-P1-A/B)."""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import timedelta

import pytest
from test_p130_idiom import FOUR, NOW, PICK, Runner, context, event, run

from yoyackbot import idiom
from yoyackbot.cooldown import SQLiteCooldownStore
from yoyackbot.settings_backup import backup_settings
from yoyackbot.state import AdmissionKind, ChannelStates, CooldownKind
from yoyackbot.watch_store import SQLiteWatchStore


def stores(path, seconds=300):
    return (SQLiteCooldownStore(path, duration_seconds=seconds),
            SQLiteCooldownStore(path, duration_seconds=seconds, table="idiom_cooldowns"))


def count(path, table: str) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# T131-P1-A ------------------------------------------------------------------------------

def test_success_posts_only_the_answer_line(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([FOUR, PICK]))
    assert run(ctx, event(ctx)) == ["말하자면 우왕좌왕? 🎯"]
    assert not hasattr(idiom, "START_NOTICE")
    assert count(ctx.path, "idiom_cooldowns") == 1 and count(ctx.path, "summary_cooldowns") == 0


# T131-P1-B ------------------------------------------------------------------------------

@pytest.mark.parametrize(("first", "other"), [
    (CooldownKind.IDIOM, CooldownKind.SUMMARY), (CooldownKind.SUMMARY, CooldownKind.IDIOM),
])
def test_each_command_has_its_own_cooldown(tmp_path, first, other) -> None:
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({2}))
    summary, idioms = stores(path)

    async def scenario():
        states = ChannelStates(summary, idiom_cooldowns=idioms, clock=lambda: NOW)
        assert (await states.admit(1, 2, kind=first)).kind is AdmissionKind.ACCEPTED
        busy = await states.admit(1, 2, kind=other)  # one channel slot for both commands
        assert busy.kind is AdmissionKind.BUSY
        await states.finish_success(1, 2, NOW, first)
        blocked = await states.admit(1, 2, kind=first)
        assert blocked.kind is AdmissionKind.COOLDOWN and blocked.remaining_seconds == 300
        assert (await states.admit(1, 2, kind=other)).kind is AdmissionKind.ACCEPTED
        await states.finish(1, 2)
        # A restart reads each table again.
        later = ChannelStates(summary, idiom_cooldowns=idioms, clock=lambda: NOW + timedelta(seconds=100))
        assert (await later.admit(1, 2, kind=first)).remaining_seconds == 200
        assert (await later.admit(1, 2, kind=other)).kind is AdmissionKind.ACCEPTED

    asyncio.run(scenario())


def test_without_an_idiom_store_there_is_no_idiom_cooldown(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({2}))

    async def scenario():
        states = ChannelStates(stores(path)[0], clock=lambda: NOW)
        await states.admit(1, 2, kind=CooldownKind.IDIOM)
        await states.finish_success(1, 2, NOW, CooldownKind.IDIOM)
        assert (await states.admit(1, 2, kind=CooldownKind.IDIOM)).kind is AdmissionKind.ACCEPTED

    asyncio.run(scenario())
    with pytest.raises(ValueError):
        SQLiteCooldownStore(path, table="messages")


def test_idiom_success_leaves_summaries_free(tmp_path, monkeypatch) -> None:
    ctx = context(tmp_path, monkeypatch, 5, Runner([FOUR, PICK]))

    async def scenario():
        try:
            await ctx.client.on_message(event(ctx))
            await ctx.client.on_message(event(ctx))
            states = ctx.client.summary_workflow.states
            assert (await states.admit(1, 2)).kind is AdmissionKind.ACCEPTED
            await states.finish_success(1, 2, NOW)
            assert (await states.admit(1, 2)).kind is AdmissionKind.COOLDOWN
            assert (await states.admit(1, 2, kind=CooldownKind.IDIOM)).kind is AdmissionKind.COOLDOWN
        finally:
            await ctx.client.close()

    asyncio.run(scenario())
    sent = [call.args[0] for call in ctx.channel.send.await_args_list]
    seconds = ctx.client.settings.success_cooldown_seconds
    assert sent[0] == "말하자면 우왕좌왕? 🎯" and sent[1] == idiom.cooldown_notice(seconds)
    assert len(ctx.runner.calls) == 2


def test_cleanup_and_backup(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10, 11, 12}))
    watches.replace(2, frozenset({20}))
    _, idioms = stores(path)
    for guild, channel in ((1, 10), (1, 11), (1, 12), (2, 20)):
        idioms.record_success(guild, channel, NOW)
    backup = json.loads(backup_settings(path, tmp_path / "backups").read_text())
    assert "idiom_cooldowns" not in backup and backup["cooldowns"] == []
    watches.replace(1, frozenset({10, 11}))
    assert count(path, "idiom_cooldowns") == 3
    watches.remove_channel(1, 11)
    assert count(path, "idiom_cooldowns") == 2
    watches.remove_guild(2)
    assert count(path, "idiom_cooldowns") == 1
    # 1.3.0 unwatches with plain SQL and does not know the table; opening again prunes it.
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DELETE FROM watched_channels WHERE guild_id=1 AND channel_id=10")
    SQLiteWatchStore(path)
    assert count(path, "idiom_cooldowns") == 0
