"""1.3.1-P3: `/속도 설정` turns the fast service tier on for one server only (T131-P3-A/B)."""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from datetime import timedelta
from unittest.mock import AsyncMock

import discord
import pytest
from discord import app_commands
from rating_fakes import candidates
from test_codex_runner import runner as sandbox_runner
from test_p130_idiom import FOUR, PICK
from test_p130_idiom import Runner as IdiomRunner
from test_p130_idiom import context as idiom_context
from test_p130_idiom import event as idiom_event
from test_p130_rating_judge import BODY, NOW, OWN, ROWS, TEN, Runner, settings, workflow_context
from test_p130_tone import interaction, rejected

from yoyackbot.channel_config import NOT_ALLOWED
from yoyackbot.codex import FAST_SERVICE_TIER, CodexContract
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import _FAST, fast_tier
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryRequest
from yoyackbot.input_files import InputWorkspace
from yoyackbot.manager_roles import MemoryManagerRoleStore
from yoyackbot.settings_backup import backup_settings, restore_settings
from yoyackbot.speed import SQLiteSpeedStore
from yoyackbot.speed_config import (
    CLOSED,
    DENIED,
    EXPIRED,
    TURNED_OFF,
    TURNED_ON,
    Choose,
    Close,
    install_speed_command,
    speed_message,
)
from yoyackbot.watch_store import SQLiteWatchStore

TIER = f'service_tier="{FAST_SERVICE_TIER}"'


class Recording(Runner):
    """The 1.3.0 judge runner, noting whether each call ran with the fast tier."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.fast: list[bool] = []

    async def execute(self, workspace, prompt):
        self.fast.append(_FAST.get())
        return await super().execute(workspace, prompt)


class IdiomRecording(IdiomRunner):
    def __init__(self, answers) -> None:
        super().__init__(answers)
        self.fast: list[bool] = []

    async def execute(self, workspace, prompt):
        self.fast.append(_FAST.get())
        return await super().execute(workspace, prompt)


# T131-P3-A ------------------------------------------------------------------------------

def test_the_contract_adds_the_tier_only_when_asked(tmp_path) -> None:
    base = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "medium")
    paths = {"working_directory": tmp_path, "output_file": tmp_path / "out.txt", "restricted": True}
    plain = base.arguments(**paths)
    fast = CodexContract(base.executable, base.model, base.reasoning_effort, FAST_SERVICE_TIER).arguments(**paths)
    assert TIER not in plain and fast.count(TIER) == 1
    assert fast == plain[:6] + ["--config", TIER] + plain[6:]
    assert "model_reasoning_effort=medium" in fast and "gpt-6-luna" in fast and 'web_search="disabled"' in fast


def test_the_sandbox_command_follows_the_request_flag(tmp_path) -> None:
    isolated = sandbox_runner(tmp_path)

    async def one(enabled: bool) -> tuple[bool, bool]:
        with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
            async with fast_tier(enabled):
                await asyncio.sleep(0)  # let the other request interleave
                inside = TIER in isolated.command(workspace)
            return inside, TIER in isolated.command(workspace)

    async def scenario():
        return await asyncio.gather(one(True), one(False), one(True))

    assert asyncio.run(scenario()) == [(True, False), (False, False), (True, False)]
    assert _FAST.get() is False


@pytest.mark.parametrize("fast", [True, False])
def test_all_five_summary_calls_use_the_same_tier(tmp_path, fast) -> None:
    leaked = "- **__P1__**: 라면을 꺼냈소."
    runner = Recording([leaked, BODY], [candidates(*TEN[:2]), candidates(TEN[8])], ["비슷함: 1, 2\n선택: 없음"])
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]
    asyncio.run(engine.summarize(ROWS, fast=fast))
    assert runner.kinds == ["summary", "summary", "cands", "judge", "cands"]
    assert runner.fast == [fast] * 5


@pytest.mark.parametrize("fast", [True, False])
def test_all_three_idiom_calls_use_the_same_tier(tmp_path, fast) -> None:
    runner = IdiomRecording(["형식이 틀린 답", FOUR, PICK])
    engine = CodexSummaryEngine(settings(tmp_path), runner)  # type: ignore[arg-type]
    rows = [MessageRecord(n, 1, 2, 7, "가람", f"대화 {n}", NOW - timedelta(minutes=5 - n)) for n in range(1, 4)]
    assert asyncio.run(engine.idiom(rows, fast=fast)).calls == 3
    assert runner.fast == [fast] * 3


@pytest.mark.parametrize(("servers", "expected"), [((1,), "fast"), ((2,), "standard"), ((), "standard")])
def test_the_summary_workflow_reads_this_servers_setting(tmp_path, monkeypatch, caplog, servers, expected) -> None:
    caplog.set_level(logging.INFO)
    runner = Recording([f"{BODY}\n\n{OWN}"], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 3"])

    async def scenario():
        workflow, channel, lease, _ratings = workflow_context(tmp_path, monkeypatch, runner)
        for guild in servers:
            workflow.speeds.set(guild, True)
        request = SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1)))
        await workflow.run(request, channel, lease, AsyncMock())

    asyncio.run(scenario())
    assert runner.fast == [expected == "fast"] * 3
    record = json.loads(next(r.message for r in caplog.records if '"summary_request"' in r.message))
    assert record["speed"] == expected and record["outcome"] == "success"


def test_an_unreadable_setting_means_the_standard_tier(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    runner = Recording([f"{BODY}\n\n{OWN}"], [candidates(*TEN[:3])], ["비슷함: 없음\n선택: 3"])

    def broken(_guild_id):
        raise sqlite3.OperationalError("locked")

    async def scenario():
        workflow, channel, lease, _ratings = workflow_context(tmp_path, monkeypatch, runner)
        workflow.speeds.fast = broken
        request = SummaryRequest(1, 2, 3, RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1)))
        await workflow.run(request, channel, lease, AsyncMock())

    asyncio.run(scenario())
    assert runner.fast == [False] * 3 and "speed_read_failed" in caplog.text
    assert '"speed":"standard"' in caplog.text and '"outcome":"success"' in caplog.text


def test_the_idiom_workflow_reads_this_servers_setting(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    ctx = idiom_context(tmp_path, monkeypatch, 5, IdiomRecording([FOUR, PICK]))
    SQLiteSpeedStore(ctx.path).set(1, True)

    async def scenario():
        try:
            await ctx.client.on_message(idiom_event(ctx))
        finally:
            await ctx.client.close()

    asyncio.run(scenario())
    assert ctx.runner.fast == [True, True]
    record = json.loads(next(r.message for r in caplog.records if '"idiom_request"' in r.message))
    assert record["speed"] == "fast" and record["outcome"] == "success"


# T131-P3-B ------------------------------------------------------------------------------

def setup(tmp_path):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({10}))
    speeds = SQLiteSpeedStore(path)
    tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
    install_speed_command(tree, speeds, MemoryManagerRoleStore())
    command = tree.get_command("속도").get_command("설정")  # type: ignore[union-attr]
    return path, speeds, command


def button(view, kind, label=None):
    return next(c for c in view.children if isinstance(c, kind) and (label is None or c.label == label))


def test_open_turn_on_and_off(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)
    _path, speeds, command = setup(tmp_path)
    assert command.parent.guild_only and getattr(command.callback, "__yoyack_gated__", False)
    assert speeds.fast(1) is False  # off by default

    async def press(fast: bool) -> str:
        opened = interaction()
        await command.callback(opened)
        view = opened.edit_original_response.await_args.kwargs["view"]
        assert opened.edit_original_response.await_args.kwargs["content"] == speed_message(speeds.fast(1))
        assert [c.label for c in view.children] == ["켜기", "끄기", "닫기"]
        click = interaction()
        await button(view, Choose, "켜기" if fast else "끄기").callback(click)
        assert view.is_finished()
        return click.edit_original_response.await_args.kwargs["content"]

    async def scenario():
        on = await press(True)
        assert on.startswith(TURNED_ON) and "켜짐" in on and speeds.fast(1) and not speeds.fast(2)
        again = await press(True)
        assert again.startswith(TURNED_ON) and speeds.fast(1)
        off = await press(False)
        assert off.startswith(TURNED_OFF) and "꺼짐" in off and not speeds.fast(1)

    asyncio.run(scenario())
    assert "speed_saved fast=true" in caplog.text and "speed_saved fast=false" in caplog.text
    assert speed_message(False).startswith("🐢 빠른 모드: 꺼짐(기본)")


def test_permissions_owner_and_expiry(tmp_path) -> None:
    _path, speeds, command = setup(tmp_path)

    async def scenario():
        member = interaction(admin=False)
        await command.callback(member)
        assert rejected(member) == NOT_ALLOWED
        member.edit_original_response.assert_not_awaited()
        manager = interaction(admin=False, roles=(55,))
        command_roles = MemoryManagerRoleStore()
        command_roles.replace(1, frozenset({55}))
        tree = app_commands.CommandTree(discord.Client(intents=discord.Intents.none()))
        install_speed_command(tree, speeds, command_roles)
        await tree.get_command("속도").get_command("설정").callback(manager)  # type: ignore[union-attr]
        assert manager.edit_original_response.await_args.kwargs["view"] is not None

        opened = interaction()
        await command.callback(opened)
        view = opened.edit_original_response.await_args.kwargs["view"]
        stranger = interaction(user_id=8)
        await button(view, Choose, "켜기").callback(stranger)
        assert rejected(stranger) == DENIED and not speeds.fast(1)
        revoked = interaction(admin=False)
        await button(view, Choose, "켜기").callback(revoked)
        assert rejected(revoked) == NOT_ALLOWED and not speeds.fast(1)
        view.expires_at = 0
        late = interaction()
        await button(view, Choose, "켜기").callback(late)
        assert rejected(late) == EXPIRED and not speeds.fast(1)

        shut = interaction()
        await command.callback(shut)
        closing_view = shut.edit_original_response.await_args.kwargs["view"]
        click = interaction()
        await button(closing_view, Close).callback(click)
        assert click.response.edit_message.await_args.kwargs["content"] == CLOSED and closing_view.is_finished()

    asyncio.run(scenario())


def test_guild_removal_backup_and_restore(tmp_path) -> None:
    path, speeds, _command = setup(tmp_path)
    watches = SQLiteWatchStore(path)
    watches.replace(2, frozenset({20}))
    speeds.set(1, True)
    speeds.set(2, True)
    backup = backup_settings(path, tmp_path / "backups")
    data = json.loads(backup.read_text())
    assert [row[0] for row in data["fast_mode"]] == [1, 2]
    restored = tmp_path / "restored.sqlite"
    restore_settings(backup, restored, live_database=path)
    assert SQLiteSpeedStore(restored).fast(1) and SQLiteSpeedStore(restored).fast(2)
    del data["fast_mode"]  # a 1.3.0 backup
    backup.write_text(json.dumps(data))
    older = tmp_path / "older.sqlite"
    restore_settings(backup, older, live_database=path)
    assert not SQLiteSpeedStore(older).fast(1)
    watches.remove_guild(2)
    assert speeds.fast(1) and not speeds.fast(2)
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM guild_fast_mode").fetchone() == (1,)
    with pytest.raises(ValueError):
        speeds.set(0, True)
