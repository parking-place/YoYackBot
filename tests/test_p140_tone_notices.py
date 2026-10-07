"""1.4.0-P5: each server's notices rewritten for its tone (T140-P5-A/B)."""

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from test_p140_audit_log import client_with, entry
from test_p140_execute_command import execute, member, world
from test_role_config import guild as fake_guild
from test_role_config import interaction as fake_interaction

from yoyackbot import errors, idiom, workflow
from yoyackbot.backfill import NOT_READY_NOTICE, READY_NOTICE, START_NOTICE, CollectionProgress
from yoyackbot.channel_config import reject, selection_summary
from yoyackbot.channel_list import (
    DM_DELIVERED_NOTICE,
    DM_FAILED_NOTICE,
    channel_list_messages,
)
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import _EFFORT
from yoyackbot.collection import EMPTY_NOTICE
from yoyackbot.collection_status import collection_lines, not_ready_detail
from yoyackbot.config import Settings
from yoyackbot.cooldown import cooldown_notice
from yoyackbot.domain import RangeRequest, RequestKind, SummaryMode, SummaryResult
from yoyackbot.execute_command import (
    BAD_TIME,
    BOT_CANNOT,
    BOT_TARGET,
    HIGHER,
    LONG_REASON,
    NOT_ALLOWED,
    PROTECTED,
    SELF,
)
from yoyackbot.execute_command import FAILED as EXECUTE_FAILED
from yoyackbot.execute_command import READ_FAILED as EXECUTE_READ_FAILED
from yoyackbot.execution_config import (
    ADMIN_ONLY,
    AUDIT_WARNING,
    CLOSED,
    INVALID_CHANNEL,
    channel_message,
    roles_message,
)
from yoyackbot.execution_log import log_message, timeout_event
from yoyackbot.notice_writer import (
    BATCH_SIZE,
    NOTICE_PROMPT,
    SQLiteNoticeStore,
    parse_answer,
    rewrite_notices,
)
from yoyackbot.notices import BOOK, CATALOG, MESSAGE_LIMIT, localize, problem, render, unmatched
from yoyackbot.parser import (
    HELP_MOVED_NOTICE,
    REQUEST_TOO_LONG_NOTICE,
    USAGE_NOTICE,
    CommandLimitError,
    OptionKind,
    help_text,
    parse_option,
    validate_option,
)
from yoyackbot.reply_range import (
    LOOKUP_FAILED_NOTICE,
    MISSING_NOTICE,
    OTHER_CHANNEL_NOTICE,
    too_many_notice,
    too_old_notice,
)
from yoyackbot.role_config import role_summary
from yoyackbot.scope import RangeScope, busy_notice, start_notice
from yoyackbot.settings_backup import BackupError, backup_settings, restore_settings
from yoyackbot.speed_config import speed_message
from yoyackbot.status_report import StatusReport, status_message
from yoyackbot.summary_format import format_summary, range_header
from yoyackbot.tone import SQLiteToneStore
from yoyackbot.tone_config import NOTICES_FAILED, NOTICES_WRITING, notices_report, tone_message
from yoyackbot.usage import (
    USAGE_EXHAUSTED_NOTICE,
    USAGE_UNAVAILABLE_NOTICE,
    UsageSnapshot,
    usage_message,
)
from yoyackbot.watch_gate import UNAVAILABLE_NOTICE, UNWATCHED_NOTICE
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)
TONE = "점잖은 보고서체로, '~습니다' 존댓말로 쓰시오."


@pytest.fixture(autouse=True)
def empty_book():
    BOOK.load({})
    yield
    BOOK.load({})


def toned(text: str) -> str:
    """A synthetic rewrite that keeps every rule (placeholders, commands, numbers, emoji)."""
    return text.rstrip() + " ~습니다"


def table_for(*keys: str) -> dict[str, str]:
    return {key: toned(CATALOG[key].text) for key in (keys or CATALOG)}


def state(**changes):
    values = {"phase": "collecting", "blocked_reason": None, "first_watch": False,
              "ready_notice_id": None, "retry_at_us": 0}
    values.update(changes)
    return SimpleNamespace(**values, ready=values["phase"] == "ready")


# T140-P5-A: the catalog ------------------------------------------------------------------

def rendered_notices() -> list[str]:
    """Every notice builder with sample values (idiom notices are not here on purpose)."""
    scopes = [RangeScope(OptionKind.HOURS, 2), RangeScope(OptionKind.MINUTES, 30),
              RangeScope(OptionKind.COUNT, 100), RangeScope(OptionKind.TODAY),
              RangeScope(OptionKind.DAYS, 3), RangeScope(OptionKind.WEEKS, 1),
              RangeScope(OptionKind.REPLY)]
    texts = [help_text(), help_text(Settings.from_environment(
        {"DISCORD_BOT_TOKEN": "x", "YOYACK_MAX_DAYS": "1"})), HELP_MOVED_NOTICE, USAGE_NOTICE,
        REQUEST_TOO_LONG_NOTICE, cooldown_notice(75), errors.BUSY_NOTICE, *errors.USER_MESSAGES.values(),
        EMPTY_NOTICE, UNWATCHED_NOTICE, UNAVAILABLE_NOTICE, START_NOTICE, READY_NOTICE, NOT_READY_NOTICE,
        workflow.FAILED_NOTICE, workflow.INVALIDATED_NOTICE, workflow.QUEUE_FULL_NOTICE,
        workflow.QUEUE_TIMEOUT_NOTICE, workflow.QUEUE_CLOSED_NOTICE, workflow.INPUT_TOO_LARGE_NOTICE,
        OTHER_CHANNEL_NOTICE, MISSING_NOTICE, LOOKUP_FAILED_NOTICE, too_old_notice(30),
        too_many_notice(2000), USAGE_UNAVAILABLE_NOTICE, USAGE_EXHAUSTED_NOTICE,
        DM_DELIVERED_NOTICE, DM_FAILED_NOTICE, *channel_list_messages([]),
        *channel_list_messages(["잡담", "공지"]),
        "🚧 요약 요청을 해석했소. 실제 요약 기능은 아직 준비 중이오. 🛠️",
    ]
    for mode in SummaryMode:
        for scope in scopes:
            texts += [start_notice(scope, mode), busy_notice(scope, mode)]
    texts.append(start_notice(RangeScope(OptionKind.REPLY, ignored_range=True), SummaryMode.SHORT))
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x"})
    for option in ("100000개", "9999분", "999일"):
        with pytest.raises(CommandLimitError) as caught:
            validate_option(parse_option(option), settings)
        texts.append(str(caught.value))
    for healthy in (True, False):
        texts.append(status_message(StatusReport(healthy, 3, 1234, 5_000_000, "gpt-6-luna", NOW - timedelta(
            minutes=5), True), NOW))
    texts.append(status_message(StatusReport(True, None, None, None, None, None, False), NOW))
    texts.append(status_message(StatusReport(True, 1, 1, 1, "m", None, True), NOW))
    for snapshot in (UsageSnapshot(50, 80), UsageSnapshot(5, None), UsageSnapshot(None, 9)):
        texts.append(usage_message(snapshot))
    ago = NOW - timedelta(hours=2)
    for item, worker in (
        (None, "running"),
        (CollectionProgress(state(), False, 3, ago, 10), "stopped"),
        (CollectionProgress(state(), True, None, None, 0), "running"),
        (CollectionProgress(state(retry_at_us=int((NOW + timedelta(minutes=5)).timestamp() * 1e6)),
                            False, 1, NOW - timedelta(seconds=5), 2), "running"),
        (CollectionProgress(state(blocked_reason="permission"), False, 1, None, 2), "running"),
        (CollectionProgress(state(blocked_reason="other"), False, 1, None, 2), "running"),
        (CollectionProgress(state(phase="ready"), False, 1, None, 2), "running"),
        (CollectionProgress(state(phase="ready", first_watch=True), False, 1, None, 2), "running"),
    ):
        texts.append("\n".join(collection_lines(item, now=NOW, cache_available=True, worker=worker)))
        texts.append(f"{NOT_READY_NOTICE}\n" + not_ready_detail(
            item, now=NOW, cache_available=False, worker=worker))
    home = SimpleNamespace(
        id=1, me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=False)),
        get_channel=lambda cid: SimpleNamespace(id=cid, mention=f"<#{cid}>") if cid != 11 else None,
        get_role=lambda rid: SimpleNamespace(id=rid, mention=f"<@&{rid}>"),
    )
    texts += [
        selection_summary(home, [10, 11]), selection_summary(home, []), role_summary(home, []),
        role_summary(home, [70]), channel_message(home, None), channel_message(home, 10),
        roles_message(home, set()), roles_message(home, {70}), speed_message(True), speed_message(False),
        "\n".join(line for line in tone_message(None).splitlines() if not line.startswith(">")),
        "\n".join(line for line in tone_message("x").splitlines() if not line.startswith(">")),
        NOTICES_WRITING, notices_report(10, 0), notices_report(8, 2), notices_report(0, 10),
        ADMIN_ONLY, AUDIT_WARNING, CLOSED, INVALID_CHANNEL, NOT_ALLOWED, BAD_TIME, LONG_REASON, SELF,
        BOT_TARGET, PROTECTED, HIGHER, BOT_CANNOT, EXECUTE_FAILED, EXECUTE_READ_FAILED,
        "⚔️ <@5>을(를) 2시간 30분 동안 처형했소. 📝 사유: 내맴",
    ]
    for before, after, reason in ((None, NOW + timedelta(minutes=5), "도배"),
                                  (NOW + timedelta(minutes=1), NOW + timedelta(hours=1), None),
                                  (NOW + timedelta(minutes=1), None, "봐줌")):
        texts.append(log_message(timeout_event(entry(before, after, reason=reason)), 501))
        texts.append(log_message(timeout_event(entry(before, after, reason=reason)), None))
    request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
    texts += [range_header(request, [], ZoneInfo("Asia/Seoul")),
              range_header(request, [], ZoneInfo("Asia/Seoul"), posted_at=NOW + timedelta(minutes=3))]
    return texts


def test_every_notice_builder_is_in_the_catalog() -> None:
    for text in rendered_notices():
        # channel names in the DM list are data, not notices
        assert [line for line in unmatched(text) if not line.startswith(" - 💬 ")] == [], text


def test_idiom_notices_stay_fixed() -> None:
    for name in dir(idiom):
        value = getattr(idiom, name)
        if name.endswith("_NOTICE") and isinstance(value, str):
            assert unmatched(value), name           # not a catalog notice, so never rewritten
    assert "!!말하자면" not in " ".join(e.text for e in CATALOG.values() if e.key != "speed.explain")


def test_keys_texts_and_placeholders_are_sane() -> None:
    texts = [notice.text for notice in CATALOG.values()]
    assert len(texts) == len(set(texts)) and len(CATALOG) >= 150
    for notice in CATALOG.values():
        assert len(notice.literal.strip()) >= 2, notice.key           # never a bare placeholder
        assert problem(notice, notice.text) is None, notice.key       # the default passes its checks
        assert problem(notice, toned(notice.text)) is None, notice.key


# T140-P5-A: rewrite, checks, storage -----------------------------------------------------

def fake_ask(log: list, *, transform=toned, fail_batch: int | None = None):
    async def ask(prompt: str, data: bytes) -> str:
        lines = [json.loads(line) for line in data.decode().splitlines()]
        log.append((prompt, lines))
        if fail_batch is not None and len(log) - 1 == fail_batch:
            raise RuntimeError("model down")
        return "\n".join(json.dumps({"key": item["key"], "text": transform(item["text"])},
                                    ensure_ascii=False) for item in lines if item["type"] == "notice")
    return ask


def test_rewrite_runs_batches_with_the_tone_only() -> None:
    calls: list = []
    result = asyncio.run(rewrite_notices(TONE, fake_ask(calls)))
    assert result.table == table_for() and result.kept == 0 and result.failed_calls == 0
    assert len(calls[0][1]) == 2 and calls[0][1][1]["key"] == "help"
    assert all(len(lines) - 1 <= BATCH_SIZE for _, lines in calls)
    for prompt, lines in calls:
        assert prompt == NOTICE_PROMPT and lines[0] == {"type": "tone", "text": TONE}
        assert {line["type"] for line in lines} == {"tone", "notice"}   # no conversation at all
    hinted = next(line for _, lines in calls for line in lines if line.get("key") == "summary.start")
    assert set(hinted["hints"]) == {"scope", "mode"}


def test_notice_calls_run_at_high(tmp_path) -> None:
    efforts = []

    class Runner:
        contract = SimpleNamespace(reasoning_effort="medium", model="gpt-6-luna")

        async def execute(self, workspace, prompt):
            efforts.append(_EFFORT.get())
            assert workspace.inline and "<<<자료" in prompt
            return "{}"

    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_INPUT_DIR": str(tmp_path / "in")})
    engine = CodexSummaryEngine(settings, Runner())
    asyncio.run(engine.rewrite_notices(NOTICE_PROMPT, b'{"type":"tone","text":"x"}\n'))
    assert efforts == ["high"]


@pytest.mark.parametrize(("key", "text", "reason"), [
    ("summary.start", "📝 {scope} 요약하겠습니다. ✍️", "placeholder"),
    ("summary.start", "📝 {scope} {scope} 채팅을 {mode}요약 ✍️", "placeholder"),
    ("summary.busy", "⏳ 요약중입니다 {잠시}", "brace"),
    ("watch.unwatched", "👀 이 채널은 아직 안 봅니다. `/채널설정`으로 정하세요.", "command"),
    ("help.moved", "📜 사용법은 /도움 으로 보세요. 🙈", "command"),
    ("execute.long_reason", "✂️ 사유는 500자까지만 쓰세요. 📏", "number"),
    ("summary.busy", "⏳ 요약중입니다.\n좀 기다리세요.", "lines"),
    ("summary.busy", "⏳ " + "기다리세요 " * 40, "length"),
    ("summary.busy", "⏳ 요약중입니다 @everyone", "mention"),
    ("summary.busy", "⏳ 요약중입니다 <@1>", "mention"),
    ("summary.busy", "⏳ 요약중입니다 https://example.invalid", "mention"),
    ("summary.busy", "⏳ 요약중이니 기다려라 이 짱깨야", "hate"),
    ("summary.busy", "요약중입니다. 🙏", "emoji"),
    ("summary.busy", "   ", "empty"),
])
def test_checks_reject_unsafe_rewrites(key, text, reason) -> None:
    assert problem(CATALOG[key], text) == reason


def test_failed_batches_and_bad_entries_keep_the_defaults() -> None:
    calls: list = []
    broken = {"summary.busy", "help.moved"}

    def transform(text):
        return "엉망 {x}" if any(CATALOG[key].text == text for key in broken) else toned(text)

    last = -(-(len(CATALOG) - 1) // BATCH_SIZE)         # the help, then the rest in batches
    result = asyncio.run(rewrite_notices(TONE, fake_ask(calls, transform=transform, fail_batch=last)))
    failed_keys = {line["key"] for line in calls[last][1] if line["type"] == "notice"}
    assert result.failed_calls == 1 and result.reasons == {"placeholder": 2}
    assert not (failed_keys | broken) & set(result.table)
    assert result.kept == len(CATALOG) - len(result.table) == len(failed_keys | broken)


def test_parse_answer_takes_only_json_lines() -> None:
    answer = '```json\n{"key": "a", "text": "가"},\n잡담\n{"key": "b"}\n{"key": "a", "text": "나"}\n```'
    assert parse_answer(answer) == {"a": "가"}


def db(tmp_path):
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path)
    return path, SQLiteToneStore(path), SQLiteNoticeStore(path)


def test_store_keeps_rows_only_for_the_current_tone(tmp_path) -> None:
    path, tones, store = db(tmp_path)
    version = tones.save(1, TONE, expected_version=0)
    tones.save(2, TONE, expected_version=0)
    assert store.missing() == [(1, version, TONE), (2, 1, TONE)]
    assert store.replace(1, version, table_for("summary.busy")) is True
    assert store.current() == {1: table_for("summary.busy")} and [g for g, *_ in store.missing()] == [2]
    newer = tones.save(1, TONE + " 더", expected_version=version)
    assert store.current() == {} and store.replace(1, version, table_for()) is False   # stale
    assert store.replace(1, newer, table_for("summary.empty")) and store.current()[1] == table_for("summary.empty")
    tones.save(1, None, expected_version=newer)                                  # reset
    assert store.current() == {} and store.replace(1, newer + 1, table_for()) is False
    store.clear(1)
    assert store.replace(2, 1, table_for("summary.busy"))
    assert store.keep_only([1]) == 1 and store.current() == {}
    assert store.replace(2, 1, table_for("summary.busy"))
    SQLiteWatchStore(path).remove_guild(2)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM guild_notices").fetchone()[0] == 0


# T140-P5-B: sending ------------------------------------------------------------------------

def test_localize_is_per_server_and_keeps_values() -> None:
    BOOK.set(1, {"summary.start": "📝 {scope} 채팅을 {mode}요약하겠습니다. ✍️",
                 "collect.stage": "📍 수집 상태: {stage}", "collect.initial": "📥 처음 모으는 중입니다.",
                 "value.minutes_ago": "{count}분 전입니다."})
    start = start_notice(RangeScope(OptionKind.HOURS, 2), SummaryMode.LONG)
    assert localize(1, start) == "📝 2시간 채팅을 길게 요약하겠습니다. ✍️"
    assert localize(2, start) == start and localize(None, start) == start
    lines = "📍 이 채널 수집: 📥 처음 수집하는 중이오.\n🕒 마지막 진척: 3분 전이오.\n> 인용은 그대로"
    assert localize(1, lines) == "📍 수집 상태: 📥 처음 모으는 중입니다.\n🕒 마지막 진척: 3분 전입니다.\n> 인용은 그대로"
    assert localize(1, "아무 글") == "아무 글"
    assert render(errors.BUSY_NOTICE, {"summary.busy": "⏳ " + "가" * MESSAGE_LIMIT}) == errors.BUSY_NOTICE


def test_help_is_rewritten_as_a_whole() -> None:
    help_table = {"help": CATALOG["help"].text.replace("**요약 사용법**", "**요약 사용 안내입니다**")}
    BOOK.set(1, help_table)
    for settings in (None, Settings.from_environment({"DISCORD_BOT_TOKEN": "x", "YOYACK_MAX_DAYS": "1"})):
        shown = localize(1, help_text(settings))
        assert shown == help_text(settings).replace("**요약 사용법**", "**요약 사용 안내입니다**")


def test_send_points_use_the_servers_notices(tmp_path, monkeypatch) -> None:
    BOOK.set(1, table_for())
    asked = fake_interaction(home=fake_guild(1))
    asyncio.run(reject(asked, "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁"))
    assert asked.response.send_message.await_args.args[0] == "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁 ~습니다"
    other = fake_interaction(home=fake_guild(2))
    asyncio.run(reject(other, "⌛ 설정 시간이 지났소. 명령을 다시 여시오. 🔁"))
    assert other.response.send_message.await_args.args[0].endswith("🔁")
    request = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
    first = format_summary(request, [], SummaryResult("요약 본문이오.", "m", 1), ZoneInfo("Asia/Seoul"),
                           guild_id=1)[0]
    assert first.splitlines()[0].endswith("~습니다") and "요약 본문이오." in first
    plain = format_summary(request, [], SummaryResult("요약 본문이오.", "m", 1), ZoneInfo("Asia/Seoul"))[0]
    assert plain.splitlines()[0].endswith("요약이오.")
    client, home, log_channel = client_with(tmp_path, monkeypatch)
    try:
        asyncio.run(client.on_audit_log_entry_create(entry(None, NOW + timedelta(seconds=30), guild=home)))
        posted = log_channel.send.await_args.args[0]
        assert posted.splitlines()[0].endswith("~습니다") and "<@502>" in posted
        command = client.tree.get_command("도움말")
        shown = fake_interaction(home=fake_guild(1))
        asyncio.run(command.callback(shown))
        assert shown.response.send_message.await_args.args[0].endswith("~습니다")
    finally:
        asyncio.run(client.close())


class NoticeEngine:
    def __init__(self, *, fail: bool = False, gate: asyncio.Event | None = None) -> None:
        self.calls: list = []
        self.fail, self.gate = fail, gate

    async def rewrite_notices(self, prompt, data):
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("down")
        return await fake_ask(self.calls)(prompt, data)


def toned_client(tmp_path, monkeypatch, engine):
    client, _home, _channel = client_with(tmp_path, monkeypatch, channel=None)
    client.summary_workflow = SimpleNamespace(engine=engine, shutdown=AsyncMock())
    tones = SQLiteToneStore(client.settings.database_path)
    return client, tones


def opener():
    return SimpleNamespace(followup=SimpleNamespace(send=AsyncMock()))


def test_a_new_tone_rewrites_stores_and_reports(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    engine = NoticeEngine()
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    BOOK.set(1, {"summary.busy": "⏳ 옛 말투 문구"})
    version = tones.save(1, TONE, expected_version=0)
    told = opener()

    async def scenario():
        try:
            client.tone_changed(told, 1, version, TONE)
            assert not BOOK.has(1)                          # defaults while it is being written
            await asyncio.wait(set(client._notice_tasks.values()))
        finally:
            await client.close()

    asyncio.run(scenario())
    assert BOOK.table(1) == table_for() and client.notices.current() == {1: table_for()}
    report = told.followup.send.await_args
    assert report.kwargs["ephemeral"] and report.args[0] == toned(notices_report(len(CATALOG), 0))
    assert f"guild_notices_written written={len(CATALOG)} kept=0 failed_calls=0" in caplog.text
    assert "~습니다" not in caplog.text and TONE not in caplog.text


def test_failure_and_reset_fall_back_to_defaults(tmp_path, monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    client, tones = toned_client(tmp_path, monkeypatch, NoticeEngine(fail=True))
    version = tones.save(1, TONE, expected_version=0)
    client.notices.replace(1, version, table_for("summary.busy"))
    BOOK.set(1, table_for("summary.busy"))
    newer = tones.save(1, TONE + "!", expected_version=version)
    told = opener()

    async def scenario():
        try:
            client.tone_changed(told, 1, newer, TONE + "!")
            await asyncio.wait(set(client._notice_tasks.values()))
            assert not BOOK.has(1) and told.followup.send.await_args.args[0] == NOTICES_FAILED
            client.summary_workflow.engine = NoticeEngine()
            client.tone_changed(opener(), 1, newer, TONE + "!")
            await asyncio.wait(set(client._notice_tasks.values()))
            assert BOOK.has(1)
            tones.save(1, None, expected_version=newer)
            client.tone_changed(opener(), 1, newer + 1, None)
            assert not BOOK.has(1)
            await asyncio.wait(set(client._notice_tasks.values()))
        finally:
            await client.close()

    asyncio.run(scenario())
    assert client.notices.current() == {} and localize(1, errors.BUSY_NOTICE) == errors.BUSY_NOTICE
    assert "failed_calls=" in caplog.text and "guild_notices_cleared" in caplog.text


def test_a_newer_tone_cancels_the_older_rewrite(tmp_path, monkeypatch) -> None:
    gate = asyncio.Event()
    engine = NoticeEngine(gate=gate)
    client, tones = toned_client(tmp_path, monkeypatch, engine)
    first = tones.save(1, TONE, expected_version=0)
    second = tones.save(1, "반말로 써.", expected_version=first)
    told_first, told_second = opener(), opener()

    async def scenario():
        try:
            client.tone_changed(told_first, 1, first, TONE)
            await asyncio.sleep(0)
            client.tone_changed(told_second, 1, second, "반말로 써.")
            gate.set()
            await asyncio.wait(set(client._notice_tasks.values()))
        finally:
            await client.close()

    asyncio.run(scenario())
    assert not told_first.followup.send.await_count and told_second.followup.send.await_count
    assert all(lines[0]["text"] == "반말로 써." for _, lines in engine.calls)


def test_startup_loads_and_catches_up(tmp_path, monkeypatch) -> None:
    client, tones = toned_client(tmp_path, monkeypatch, NoticeEngine())
    ready = tones.save(1, TONE, expected_version=0)
    client.notices.replace(1, ready, table_for("summary.busy"))
    tones.save(2, TONE, expected_version=0)                 # saved before 1.4.0: no notices yet
    tones.save(3, TONE, expected_version=0)                 # a server the bot has left
    monkeypatch.setattr(type(client), "guilds", property(lambda self: [SimpleNamespace(id=1),
                                                                       SimpleNamespace(id=2)]))

    async def scenario():
        try:
            client.dev_guild_id = 0
            client.tree.sync = AsyncMock(return_value=[])
            client._sync_guild_commands = AsyncMock()
            await client.setup_hook()
            assert BOOK.table(1) == table_for("summary.busy") and not BOOK.has(2)
            client.notices.keep_only([1, 2])
            await client._catch_up_notices()
        finally:
            await client.close()

    asyncio.run(scenario())
    assert BOOK.table(2) == table_for() and not BOOK.has(3)


def test_backup_keeps_valid_notices(tmp_path) -> None:
    path, tones, store = db(tmp_path)
    version = tones.save(1, TONE, expected_version=0)
    store.replace(1, version, table_for("summary.busy", "help"))
    backup = backup_settings(path, tmp_path / "backups")
    data = json.loads(backup.read_text())
    assert [row[1] for row in data["notices"]] == ["help", "summary.busy"]
    restored = tmp_path / "restored.sqlite"
    restore_settings(backup, restored, live_database=path)
    assert SQLiteNoticeStore(restored).current() == {1: table_for("summary.busy", "help")}
    data["notices"].append([1, "gone.key", "옛 문구", version, 0])        # a key this release lacks
    del data["tones"]
    data["tones"] = [[1, version, TONE, 0]]
    backup.write_text(json.dumps(data))
    restore_settings(backup, tmp_path / "again.sqlite", live_database=path)
    data["notices"].append([1, "summary.empty", "{x} @everyone", version, 0])
    backup.write_text(json.dumps(data))
    with pytest.raises(BackupError):
        restore_settings(backup, tmp_path / "bad.sqlite", live_database=path)
    del data["notices"]                                                     # a 1.3.4 backup
    backup.write_text(json.dumps(data))
    restore_settings(backup, tmp_path / "old.sqlite", live_database=path)


def test_execute_answers_and_channel_list_use_the_servers_words(tmp_path) -> None:
    BOOK.set(1, table_for())
    store, home, _ = world(tmp_path)
    outcome, answer, *_ = execute(store, home, member(503, position=5))
    assert outcome == "refused" and answer == toned(SELF)
    parts = [localize(1, part) for part in channel_list_messages(["잡담"])]
    assert parts[0].startswith(toned("📡👀 지금 본인이 보고 있는 채널을 알려주겠소"))
    assert " - 💬 잡담" in parts[0] and parts[0].endswith(toned("✅ 이상이오. 🫡"))
