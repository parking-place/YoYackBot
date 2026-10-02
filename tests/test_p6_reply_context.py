"""F10: reply links inside the selected conversation only (T120-P6-A..C)."""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from rating_fakes import skip_rating_step

from yoyackbot.codex import CodexContract, CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.config import Settings
from yoyackbot.discord import YoYackClient
from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import (
    MIN_MESSAGE_LINE_BYTES,
    ConversationTooLarge,
    InputWorkspace,
    message_keys,
    serialize_conversation,
)
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.output_quality import OutputIssue, inspect_output
from yoyackbot.reply_refs import reply_target
from yoyackbot.settings_backup import backup_settings, restore_settings
from yoyackbot.summary_prompt import SUMMARY_PROMPT
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
BASE = discord.utils.time_snowflake(NOW - timedelta(hours=2))


def mid(n: int) -> int:
    return BASE + n * 1_000_000


def rec(n: int, author: int, name: str, body: str, *, to: int | None = None,
        reply: bool | None = None) -> MessageRecord:
    return MessageRecord(
        mid(n), 1, 99, author, name, body, NOW - timedelta(hours=2) + timedelta(minutes=n),
        is_reply=reply if reply is not None else to is not None,
        reply_to_message_id=mid(to) if to is not None else None,
    )


def lines(records: list[MessageRecord], **kwargs) -> list[dict]:
    data = serialize_conversation(records, channel_name="합성", range_label="합성",
                                  trigger_message_id=kwargs.pop("trigger", None),
                                  max_bytes=kwargs.pop("max_bytes", 1_000_000), **kwargs)
    return [json.loads(line) for line in data.decode().splitlines()][1:]


# T120-P6-A ------------------------------------------------------------------------------

def test_single_reply_and_crossed_questions_map_to_their_own_targets() -> None:
    single = lines([rec(1, 1, "가람", "배포 언제 하오?"), rec(2, 2, "나래", "금요일이오.", to=1)])
    assert single[0]["id"] == "M1" and "reply_to" not in single[0]
    assert single[1]["reply_to"] == "M1" and single[1]["reply"] is True and "id" not in single[1]

    crossed = lines([
        rec(1, 1, "가람", "배포 언제?"), rec(2, 3, "다온", "회의실 어디?"),
        rec(3, 2, "나래", "3층이오.", to=2), rec(4, 2, "나래", "금요일이오.", to=1),
    ])
    assert [line.get("id") for line in crossed] == ["M1", "M2", None, None]
    assert [line.get("reply_to") for line in crossed] == [None, None, "M2", "M1"]


def test_same_display_name_and_reply_chain_keep_speakers_and_targets_apart() -> None:
    chain = lines([
        rec(1, 1, "가람", "점심 국밥 어떻소?"), rec(2, 2, "가람", "국밥 말고 냉면.", to=1),
        rec(3, 1, "가람", "냉면은 줄이 길다오.", to=2),
    ])
    assert [line["speaker"] for line in chain] == ["P1", "P2", "P1"]
    assert chain[0]["display_name"] != chain[1]["display_name"]
    assert [line.get("id") for line in chain] == ["M1", "M2", None]
    assert [line.get("reply_to") for line in chain] == [None, "M1", "M2"]


def test_order_range_and_count_are_unchanged_by_links(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({99}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    plain = [rec(n, 1 + n % 2, "가람" if n % 2 else "나래", f"합성 {n}") for n in range(1, 7)]
    for item in plain:
        store.upsert(item, cached_at=NOW)
    before = [item.message_id for item in store.recent(1, 99, NOW - timedelta(days=1), NOW)]
    store.upsert(rec(7, 1, "가람", "답글", to=3), cached_at=NOW)
    after = store.recent(1, 99, NOW - timedelta(days=1), NOW)
    assert [item.message_id for item in after] == [*before, mid(7)]
    assert after[-1].reply_to_message_id == mid(3)
    newest = store.latest(1, 99, NOW - timedelta(days=1), NOW, 2)
    assert [item.message_id for item in newest] == [mid(7), mid(6)]
    assert newest[0].reply_to_message_id == mid(3)
    with closing(sqlite3.connect(path)) as connection:
        plan = " ".join(row[3] for row in connection.execute(
            "EXPLAIN QUERY PLAN SELECT m.message_id FROM messages m LEFT JOIN message_reply_refs r "
            "ON r.guild_id=m.guild_id AND r.channel_id=m.channel_id AND r.message_id=m.message_id "
            "WHERE m.guild_id=1 AND m.channel_id=99 AND m.created_at_us>=0 AND m.created_at_us<1 "
            "ORDER BY m.created_at_us, m.message_id"))
    assert "TEMP B-TREE" not in plan  # still streamed in index order (P3 bounded reads)


# T120-P6-B ------------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["out_of_range", "unknown", "trigger"])
def test_targets_outside_the_selection_are_sent_as_unknown(missing) -> None:
    question = rec(1, 1, "가람", "배포 언제?")
    if missing == "out_of_range":
        selected = [rec(2, 2, "나래", "금요일이오.", to=1)]
        trigger = None
    elif missing == "unknown":
        selected = [question, rec(2, 2, "나래", "금요일이오.", reply=True)]
        trigger = None
    else:
        selected = [question, rec(2, 2, "나래", "금요일이오.", to=1)]
        trigger = question.message_id
    result = lines(selected, trigger=trigger)
    assert all("id" not in line and "reply_to" not in line for line in result)
    assert result[-1]["reply"] is True


def discord_message(message_id: int, *, reference: object, kind=discord.MessageType.reply):
    return SimpleNamespace(id=message_id, type=kind, reference=reference)


@pytest.mark.parametrize(("reference", "expected"), [
    (SimpleNamespace(message_id=mid(1), channel_id=99, guild_id=1), mid(1)),
    (SimpleNamespace(message_id=mid(1), channel_id=99, guild_id=None), mid(1)),
    (SimpleNamespace(message_id=mid(1), channel_id=98, guild_id=1), None),
    (SimpleNamespace(message_id=mid(1), channel_id=99, guild_id=2), None),
    (SimpleNamespace(message_id=None, channel_id=99, guild_id=1), None),
    (SimpleNamespace(message_id=mid(9), channel_id=99, guild_id=1), None),
    (None, None),
])
def test_only_same_channel_earlier_targets_are_kept(reference, expected) -> None:
    assert reply_target(discord_message(mid(5), reference=reference), 1, 99) == expected
    assert reply_target(discord_message(mid(5), reference=reference,
                                        kind=discord.MessageType.default), 1, 99) is None


def test_gateway_stores_the_link_without_fetching_the_target(tmp_path, caplog) -> None:
    caplog.set_level(logging.INFO)

    async def scenario():
        path = tmp_path / "db.sqlite"
        watched = SQLiteWatchStore(path)
        watched.replace(1, frozenset({99}))
        messages = SQLiteMessageStore(path, clock=lambda: NOW)
        client = YoYackClient(watch_store=watched, message_store=messages, clock=lambda: NOW)
        channel = SimpleNamespace(type=discord.ChannelType.text, id=99, fetch_message=AsyncMock(),
                                  history=Mock())
        event = SimpleNamespace(
            id=mid(5), guild=SimpleNamespace(id=1), channel=channel, webhook_id=None,
            author=SimpleNamespace(id=3, bot=False, display_name="나래"),
            type=discord.MessageType.reply, content="금요일이오.", created_at=NOW, edited_at=None,
            attachments=(), reference=SimpleNamespace(message_id=mid(1), channel_id=99, guild_id=1),
        )
        try:
            await client.on_message(event)
        finally:
            await client.close()
        channel.fetch_message.assert_not_awaited()
        channel.history.assert_not_called()
        return messages.recent(1, 99, NOW - timedelta(hours=1), NOW + timedelta(seconds=1))

    stored, = asyncio.run(scenario())
    assert stored.reply_to_message_id == mid(1)
    assert str(mid(1)) not in caplog.text and str(mid(5)) not in caplog.text


def test_model_input_never_carries_discord_ids_and_the_budget_counts_keys() -> None:
    records = [rec(1, 1, "가람", "배포 언제?"), rec(2, 2, "나래", "금요일이오.", to=1)]
    data = serialize_conversation(records, channel_name="합성", range_label="합성",
                                  trigger_message_id=None, max_bytes=10_000)
    assert str(mid(1)) not in data.decode() and str(mid(2)) not in data.decode()
    with pytest.raises(ConversationTooLarge):
        serialize_conversation(records, channel_name="합성", range_label="합성",
                               trigger_message_id=None, max_bytes=len(data) - 1)
    assert all(len(line.encode()) + 1 >= MIN_MESSAGE_LINE_BYTES
               for line in data.decode().splitlines()[1:])
    assert "reply_to" in SUMMARY_PROMPT and "M1 같은 값은 내부 표식" in SUMMARY_PROMPT


def test_message_keys_in_output_are_retried_unless_the_chat_says_them(tmp_path) -> None:
    keys = frozenset({"M1"})
    assert inspect_output("### 🚀 배포\n- **__나래__**: M1에 답했소.", ["배포 언제?"], keys) is (
        OutputIssue.MESSAGE_KEY
    )
    assert inspect_output("### 💻 장비\n- **__나래__**: M1 맥북을 샀소.", ["M1 맥북 샀소"], keys) is None
    assert inspect_output("### 🚀 배포\n- **__나래__**: M2라고 했소.", ["배포"], keys) is None

    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        def __init__(self, answers):
            self.answers, self.calls = answers, 0

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            skip_rating_step(workspace, prompt)
            self.calls += 1
            self.last_prompt = prompt
            workspace.close()
            return self.answers.pop(0)

    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_INPUT_DIRECTORY": str(tmp_path / "in"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })
    records = [rec(1, 1, "가람", "배포 언제?"), rec(2, 2, "나래", "금요일이오.", to=1)]
    leaked = "### 🚀 배포\n- **__나래__**: M1에 금요일이라 답했소.\n\n**요약창섭의 떡밥 한줄 평가** : 빠르오."
    good = "### 🚀 배포\n- **__나래__**: 가람의 질문에 금요일이라 답했소.\n\n**요약창섭의 떡밥 한줄 평가** : 빠르오."
    runner = Runner([leaked, good])
    result = asyncio.run(CodexSummaryEngine(settings, runner).summarize(records))  # type: ignore[arg-type]
    assert result.text == good and runner.calls == 2 and "내부 메시지 표식" in runner.last_prompt
    runner = Runner([leaked, leaked])
    with pytest.raises(CodexRunError) as error:
        asyncio.run(CodexSummaryEngine(settings, runner).summarize(records))  # type: ignore[arg-type]
    assert error.value.kind is CodexFailure.OUTPUT_INVALID and runner.calls == 2


# T120-P6-C ------------------------------------------------------------------------------

def store_with_links(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    store = SQLiteMessageStore(path, clock=lambda: NOW)
    for item in (rec(1, 1, "가람", "질문"), rec(2, 2, "나래", "답", to=1), rec(3, 1, "가람", "재답", to=2)):
        store.upsert(item, cached_at=NOW)
    return path, watches, store


def links(path: Path) -> list[tuple[int, int]]:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(
            "SELECT message_id, target_id FROM message_reply_refs ORDER BY message_id").fetchall()


def test_deletes_edits_retention_and_reconcile_never_leave_or_revive_links(tmp_path) -> None:
    path, _watches, store = store_with_links(tmp_path)
    assert links(path) == [(mid(2), mid(1)), (mid(3), mid(2))]
    assert store.update_content(1, 99, mid(2), "답(수정)", edited_at=NOW, cached_at=NOW)
    assert links(path) == [(mid(2), mid(1)), (mid(3), mid(2))]  # an edit keeps the reply target
    store.delete_many(1, 99, {mid(1)})
    assert links(path) == [(mid(3), mid(2))]  # the deleted target's incoming link is gone
    store.upsert(rec(2, 2, "나래", "답", to=1), cached_at=NOW)  # stale page re-delivers the reply
    assert links(path) == [(mid(3), mid(2))]  # target is tombstoned, so no revival
    store.delete_many(1, 99, {mid(3)})
    store.upsert(rec(3, 1, "가람", "재답", to=2), cached_at=NOW)
    assert links(path) == []  # deleted source stays deleted with its link
    # Retention removes rows through the same trigger.
    store.upsert(rec(4, 1, "가람", "새 답", to=2), cached_at=NOW)
    assert links(path) == [(mid(4), mid(2))]
    store.prune_before(NOW)
    assert links(path) == []


def test_unwatch_rewatch_guild_removal_backup_and_restore(tmp_path) -> None:
    path, watches, store = store_with_links(tmp_path)
    backup = backup_settings(path, tmp_path / "backups")
    assert "reply" not in backup.read_text() and str(mid(1)) not in backup.read_text()
    restored = tmp_path / "restored.db"
    restore_settings(backup, restored, live_database=path)
    SQLiteMessageStore(restored)  # the service opens the restored database
    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM message_reply_refs").fetchone() == (0,)
    watches.replace(1, frozenset({98}))
    assert links(path) == []
    watches.replace(1, frozenset({98, 99}))
    store.upsert(rec(1, 1, "가람", "질문"), cached_at=NOW)
    assert store.recent(1, 99, NOW - timedelta(days=1), NOW)[0].reply_to_message_id is None
    store.upsert(rec(2, 2, "나래", "답", to=1), cached_at=NOW)
    watches.remove_guild(1)
    assert links(path) == []


def test_older_cache_and_older_writers(tmp_path) -> None:
    path, _watches, store = store_with_links(tmp_path)
    # An older release had no link table; its reply rows stay "reply, target unknown".
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TRIGGER message_reply_refs_cleanup")
        connection.execute("DROP TABLE message_reply_refs")
    SQLiteWatchStore(path)
    old = store.recent(1, 99, NOW - timedelta(days=1), NOW)
    assert [item.is_reply for item in old] == [False, True, True]
    assert all(item.reply_to_message_id is None for item in old)
    store.upsert(rec(2, 2, "나래", "답", to=1), cached_at=NOW)
    # An older writer deletes and upserts with plain SQL; the trigger still cleans up.
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DELETE FROM messages WHERE message_id=?", (mid(1),))
    assert links(path) == []
    store.upsert(rec(3, 1, "가람", "재답", to=2), cached_at=NOW)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("UPDATE messages SET content='수정', edited_at_us=1 WHERE message_id=?",
                           (mid(3),))
    assert links(path) == [(mid(3), mid(2))]
    # A link row left without its message (written before the trigger) is pruned on open.
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DROP TRIGGER message_reply_refs_cleanup")
        connection.execute("DELETE FROM messages WHERE message_id=?", (mid(3),))
    SQLiteWatchStore(path)
    assert links(path) == []
    assert message_keys([]) == {}


def test_real_model_fixture_builds_the_intended_links() -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_reply_context.py"
    spec = importlib.util.spec_from_file_location("evaluate_reply_context", script)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    cases = json.loads(module.FIXTURE.read_text())
    assert len(cases) == 8
    for case in cases:
        selected = module.records(case)
        data = serialize_conversation(selected, channel_name="합성", range_label="합성",
                                      trigger_message_id=None, max_bytes=100_000).decode()
        sent = [json.loads(line) for line in data.splitlines()[1:]]
        excluded = set(case.get("exclude", []))
        expected = sum(
            1 for index, row in enumerate(case["messages"], start=1)
            if index not in excluded and row.get("reply_to") and row["reply_to"] not in excluded
        )
        assert sum("reply_to" in line for line in sent) == expected, case["id"]
        assert len(sent) == len(case["messages"]) - len(excluded)
