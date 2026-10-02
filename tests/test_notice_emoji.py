"""Every user-facing notice line opens with an emoji, and the wording stays haoche (T113a)."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from yoyackbot.channel_list import EMPTY_NOTICE as CHANNEL_EMPTY_NOTICE
from yoyackbot.channel_list import LIST_FOOTER, LIST_HEADER, channel_list_messages
from yoyackbot.status_report import StatusReport, status_message
from yoyackbot.usage import (
    USAGE_EXHAUSTED_NOTICE,
    USAGE_UNAVAILABLE_NOTICE,
    UsageSnapshot,
    usage_message,
)

EMOJI = re.compile(r"^(?:\s*-\s+)?[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿←-⇿]")
HAOCHE = re.compile(r"(?:소|오|요|시오|구려|겠소|었소|았소|하오|이오)[.!?…]*(?:\.\.\.)?$")
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
# Released wordings that end differently on purpose (a header without ending, a blessing).
KEPT_ENDINGS = ("알려주겠소", "함께하길...")


def lines_of(*texts: str) -> list[str]:
    return [line for text in texts for line in text.splitlines() if line.strip()]


def strip_trailing_emoji(line: str) -> str:
    return re.sub(r"[\s\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍]+$", "", line)


def command_reply_texts() -> list[str]:
    report = StatusReport(gateway_ready=True, watched_channels=2, cached_messages=3, database_bytes=1_000_000,
                          model="gpt-6-luna / low", last_success=NOW - timedelta(minutes=3),
                          last_success_known=True)
    broken = StatusReport(gateway_ready=False, watched_channels=None, cached_messages=None, database_bytes=None,
                          model=None, last_success=None, last_success_known=False)
    return [
        usage_message(UsageSnapshot(74, 82)), usage_message(UsageSnapshot(None, 6)),
        USAGE_UNAVAILABLE_NOTICE, USAGE_EXHAUSTED_NOTICE,
        status_message(report, NOW), status_message(broken, NOW),
        *channel_list_messages(["잡담", "개발"]), CHANNEL_EMPTY_NOTICE, LIST_HEADER, LIST_FOOTER,
    ]


@pytest.mark.parametrize("line", lines_of(*command_reply_texts()))
def test_command_reply_lines_open_with_emoji(line: str) -> None:
    assert EMOJI.match(line), line


@pytest.mark.parametrize(
    "line", [line for line in lines_of(*command_reply_texts())
             if not line.lstrip().startswith("-") and ":" not in line
             and not any(kept in line for kept in KEPT_ENDINGS)],
)
def test_command_reply_sentences_keep_haoche(line: str) -> None:
    assert HAOCHE.search(strip_trailing_emoji(line)), line


# --- groups 4-13: scan every Korean string the bot can send (T113a-P2) ---------------------------

import ast
from pathlib import Path

from yoyackbot import channel_list, collection, errors, parser, watch_gate, workflow
from yoyackbot.backfill import NOT_READY_NOTICE, READY_NOTICE, START_NOTICE
from yoyackbot.cooldown import cooldown_notice
from yoyackbot.domain import SummaryMode
from yoyackbot.errors import USER_MESSAGES, FailureKind
from yoyackbot.parser import OptionKind
from yoyackbot.scope import RangeScope, busy_notice, start_notice

SOURCE = Path(__file__).resolve().parents[1] / "src" / "yoyackbot"
MESSAGE_MODULES = (
    "usage.py", "status_report.py", "channel_list.py", "scope.py", "workflow.py", "cooldown.py",
    "collection.py", "backfill.py", "watch_gate.py", "errors.py", "discord.py",
    "channel_config.py", "role_config.py", "summary_format.py", "collection_status.py",
)
HANGUL = re.compile(r"[가-힣]")
# Pieces that are glued into a line that already opens with an emoji, and Discord metadata.
FRAGMENTS = {
    "길게 ", "자세히 ", "분", "시간", "일", "주", "개", "오늘", "최근 {}개", "{}간의", "{} 분",
    "확인할 수 없소.", "방금 전이오.", "{}분 전이오.", "{}시간 전이오.", "{}일 전이오.", "기록이 없소.",
    "평온하오. 😌", "점검이 필요하오. 🚨", "{}곳이오.", "{}건이오.", "{} MB이오.",
    "오전", "오후", "{} {}시 {}분", "오늘 00시 00분", "{}년 ", "{}{}월 {}일 {}",
    "없음", "삭제된 채널", " 외 {}개", "없음(관리자만 사용)", "삭제된 역할",
    "전체 해제", "저장", "취소", "채널", "설정", "주시 채널 관리", "요약봇이 주시할 텍스트 채널을 고르오",
    "관리권한", "봇 관리 역할 관리", "요약봇 슬래시 명령어를 쓸 수 있는 역할을 고르오",
    "사용자", "현재 채널", "요청 범위", "선택한 대화", "#채널", "@역할", "@사용자",
    " (⏰ 기준: {} KST)", "다. ",
    "곧이오.", "{}분 뒤이오.", "{}시간 뒤이오.", "아직 없소.", "{}쪽이오.", "확인 불가", "{}쪽",
}


def template(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
        )
    return None


def message_templates() -> list[tuple[str, str]]:
    found = []
    for name in MESSAGE_MODULES:
        tree = ast.parse((SOURCE / name).read_text(encoding="utf-8"))
        skip: set[int] = set()
        for node in ast.walk(tree):
            # docstrings, logger calls, and HELP lines are not notices (the help has its own test)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and getattr(node.func.value, "id", "") == "LOGGER":
                skip.update(id(arg) for arg in ast.walk(node))
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_HELP_LINES" for t in node.targets):
                skip.update(id(arg) for arg in ast.walk(node))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) \
                    and node.body and isinstance(node.body[0], ast.Expr):
                skip.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if id(node) in skip or isinstance(getattr(node, "ctx", None), ast.Store):
                continue
            text = template(node)
            if text and HANGUL.search(text) and isinstance(node, (ast.Constant, ast.JoinedStr)):
                found.append((name, text))
    # parts of f-strings are visited too; keep whole templates only
    whole = {text for _name, text in found}
    return [(name, text) for name, text in found
            if not any(text != other and text in other for other in whole)]


TEMPLATES = message_templates()


def test_the_scan_sees_the_notices() -> None:
    texts = {text for _name, text in TEMPLATES}
    assert len(texts) > 60
    assert "🧊 아직은 때가 아니오. {}분 {}초 뒤에 오시오. ⏰" in texts


@pytest.mark.parametrize(("module", "text"), [item for item in TEMPLATES if item[1] not in FRAGMENTS])
def test_every_message_line_opens_with_emoji(module: str, text: str) -> None:
    for line in text.split("\n"):
        if not line.strip() or line.startswith(("{}", " - ")):
            continue
        assert EMOJI.match(line), (module, line)


def limit_error() -> str:
    from yoyackbot.config import Settings
    from yoyackbot.parser import CommandLimitError, parse_option, validate_option

    with pytest.raises(CommandLimitError) as raised:
        validate_option(parse_option("31일"), Settings.from_environment({"DISCORD_BOT_TOKEN": "x"}))
    text = str(raised.value)
    assert text == "📏 일 단위는 1부터 30까지 고르시오. `!!요약좀 도움`에서 사용법을 살펴보시오. 📜"
    return text


SCOPES = [RangeScope(OptionKind.MINUTES, 30), RangeScope(OptionKind.HOURS, 3), RangeScope(OptionKind.DAYS, 10),
          RangeScope(OptionKind.WEEKS, 1), RangeScope(OptionKind.TODAY, None), RangeScope(OptionKind.COUNT, 100)]


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("mode", list(SummaryMode))
def test_start_and_busy_notices_open_with_emoji(scope: RangeScope, mode: SummaryMode) -> None:
    for line in lines_of(start_notice(scope, mode), busy_notice(scope, mode), cooldown_notice(65)):
        assert EMOJI.match(line), line
        assert HAOCHE.search(strip_trailing_emoji(line)), line


def test_flow_notices_and_duplicates_point_at_the_real_text() -> None:
    for text in (START_NOTICE, READY_NOTICE, NOT_READY_NOTICE, collection.EMPTY_NOTICE,
                 watch_gate.UNWATCHED_NOTICE, watch_gate.UNAVAILABLE_NOTICE, workflow.BUSY_NOTICE,
                 workflow.FAILED_NOTICE, workflow.INVALIDATED_NOTICE, workflow.QUEUE_FULL_NOTICE,
                 workflow.QUEUE_TIMEOUT_NOTICE, workflow.QUEUE_CLOSED_NOTICE,
                 workflow.INPUT_TOO_LARGE_NOTICE, parser.USAGE_NOTICE, parser.REQUEST_TOO_LONG_NOTICE,
                 channel_list.EMPTY_NOTICE, limit_error(), *USER_MESSAGES.values()):
        assert EMOJI.match(text), text
    assert USER_MESSAGES[FailureKind.UNWATCHED] is watch_gate.UNWATCHED_NOTICE
    assert USER_MESSAGES[FailureKind.INVALID_OPTION] is parser.USAGE_NOTICE
    assert USER_MESSAGES[FailureKind.EMPTY] is collection.EMPTY_NOTICE
    assert USER_MESSAGES[FailureKind.BUSY] is workflow.BUSY_NOTICE is errors.BUSY_NOTICE
    assert USER_MESSAGES[FailureKind.COOLDOWN].startswith(cooldown_notice(65).split(" 01분")[0])
    assert workflow.QUEUE_TIMEOUT_NOTICE == "⌛ 요약 대기 시간이 지났소. 다시 시도하시오. 🔁"
