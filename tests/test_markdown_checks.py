"""Output checks follow the 1.1.2a markdown layout (T112a-P3)."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from yoyackbot.codex import CodexContract
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryResult
from yoyackbot.input_files import InputWorkspace
from yoyackbot.ops import RequestMetrics
from yoyackbot.output_quality import (
    RATING_LABEL,
    TopicSection,
    inspect_output,
    is_critique,
    name_underline,
    narrator_mocks_ongoing,
    narrator_uses_hate_term,
    split_rating,
    strip_emoji,
    topic_critique,
    topic_sections,
)
from yoyackbot.summary_format import format_summary, utf16_length

RATING = f"{RATING_LABEL}달력 한 장에 요란 떨 일이오? 🔥"
SHORT = """### 🚀 배포 날짜
__가람__이 ~~금요일~~ 대신 **목요일 오후 2시**로 바로잡았고 __나래__가 찬성했소. ✅ **결정**: **목요일 오후 2시** 🎉
> ↳ _배포 얘기 틈에 점심 메뉴까지, 화제가 휙휙 튀오_ 🌀

### 🧯 롤백 담당
__다온__이 롤백 담당을 물었고 다음 회의에서 정하자고 했소. ⏳ **진행 중**: 롤백 담당
> ↳ _롤백 소리만 나와도 등골이 서늘한 모양이오_ 🥶"""
LONG = """### 🚀 배포 날짜
- **__가람__**: 금요일 오후 2시를 제안했소. 📅
- **__나래__**: 반대했소. 🚫
> ↳ _요일 퀴즈였소_ 🤡

### ✅ 결정 난 거
- **목요일 오후 2시** 배포.

### ⏳ 진행 중인 거
- 롤백 담당."""
NAMES = ["가람", "나래", "다온"]


def test_quoted_critiques_are_critiques_and_source_quotes_are_not() -> None:
    assert is_critique("> ↳ _요란하오_ 🌀") and is_critique(">↳ _요란하오_") and is_critique("↳ *옛 형식*")
    assert not is_critique('> "금요일은 안 돼요"') and not is_critique("- ↳ 아님")


@pytest.mark.parametrize(
    "line",
    ["> ↳ _병신 같은 소리였소_ 🤡", "> ↳ _또 질질 끄는구려_ 🐌", "> ↳ _답은 아직 안개 속이구려_ 🤔",
     "> ↳ _다음 회의로 넘기는 솜씨가 일품이오_"],
)
def test_quoted_critique_lines_are_inspected(line: str) -> None:
    assert narrator_uses_hate_term(line) or narrator_mocks_ongoing(line)


@pytest.mark.parametrize(
    "line", ['> "병신같이 굴지 마"라고 했소', "> 결국 미뤘네", '> "아직 못 정했어요"'],
)
def test_source_quote_lines_are_still_skipped(line: str) -> None:
    assert not narrator_uses_hate_term(line) and not narrator_mocks_ongoing(line)


def test_hate_term_in_a_quoted_critique_is_an_output_issue() -> None:
    assert inspect_output(SHORT.replace("화제가 휙휙 튀오", "병신 같은 화제요"), []) is not None
    assert inspect_output(SHORT, []) is None


@pytest.mark.parametrize(
    ("text", "expected", "sections"),
    [
        (f"{SHORT}\n\n{RATING}", "all", [TopicSection(1, 1), TopicSection(1, 1)]),
        (f"{LONG}\n\n{RATING}", "all", [TopicSection(2, 1)]),
        (SHORT.replace("> ↳ _롤백 소리만 나와도 등골이 서늘한 모양이오_ 🥶", ""), "partial",
         [TopicSection(1, 1), TopicSection(1, 0)]),
        ("### 📣 안내\n안내 여부는 내일 보기로 했소.\n↳ *옛 형식 비평*", "all", [TopicSection(1, 1)]),
        ("**📣 굵은 소제목**\n내용이오.\n> ↳ _새 형식 비평_", "all", [TopicSection(1, 1)]),
        ("- 가람: 시간순 목록이오.\n\n**추가 요청 중 일부는 들어줄 수 없었소.**", "na", []),
    ],
)
def test_topics_follow_markdown_titles(text, expected, sections) -> None:
    assert topic_sections(text) == sections
    assert topic_critique(text) == expected


@pytest.mark.parametrize(
    ("text", "names", "expected"),
    [
        (SHORT, NAMES, "all"),
        (LONG, NAMES, "all"),
        (SHORT.replace("__나래__", "나래"), NAMES, "partial"),
        (SHORT.replace("__", ""), NAMES, "none"),
        ("### 🎲 잡담\n별 얘기 없었소.", NAMES, "na"),
        ("__가람이__와 __가람__이 다퉜소.", ["가람", "가람이"], "all"),
        ("가람이가 웃었소. __가람__도 웃었소.", ["가람", "가람이"], "partial"),
        ("__사용자 (1)__이 물었소.", ["사용자 (1)"], "all"),
        ("> ↳ _가람 얘기는 빼고 비꼬오_\n" + RATING + " 가람", ["가람"], "na"),
        ('나래는 "가람 왔어?"라고 물었소.', ["가람", "나래"], "none"),
        ("`가람` 코드는 세지 않소. __나래__만 세오.", ["가람", "나래"], "all"),
        ("민이 왔소. __민__도.", ["민"], "na"),
    ],
)
def test_name_underline_metric(text, names, expected) -> None:
    assert name_underline(text, names) == expected


def test_strip_emoji_keeps_markdown_titles_and_quoted_critiques() -> None:
    assert strip_emoji(SHORT).splitlines()[:3] == [
        "### 배포 날짜",
        "__가람__이 ~~금요일~~ 대신 **목요일 오후 2시**로 바로잡았고 __나래__가 찬성했소. **결정**: **목요일 오후 2시**",
        "> ↳ _배포 얘기 틈에 점심 메뉴까지, 화제가 휙휙 튀오_",
    ]
    assert topic_critique(strip_emoji(f"{SHORT}\n\n{RATING}")) == "all"


def test_rating_still_splits_after_quoted_critiques() -> None:
    body, rating = split_rating(f"{SHORT}\n\n{RATING}")
    assert body == SHORT and rating == RATING


def test_long_markdown_summary_splits_on_lines() -> None:
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    request = RangeRequest(RequestKind.TIME, now, start=now - timedelta(hours=1))
    text = "\n\n".join(SHORT.replace("배포 날짜", f"배포 날짜 {n}") for n in range(30)) + f"\n\n{RATING}"
    parts = format_summary(request, ROWS, SummaryResult(text, "synthetic", 1),
                           ZoneInfo("Asia/Seoul"), posted_at=now)
    assert len(parts) > 1 and all(utf16_length(part) <= 1900 for part in parts)
    for part in parts:
        for line in part.splitlines():
            if line.startswith(">"):
                assert line.startswith("> ↳ _") and line.rstrip().endswith(("🌀", "🥶")), line
    assert parts[-1].rstrip().endswith(RATING)


ROWS = [
    MessageRecord(1, 1, 10, 100, "가람", "금요일 배포 어때요?", datetime(2026, 10, 1, 11, tzinfo=UTC)),
    MessageRecord(2, 1, 10, 101, "나래", "주말은 안 돼요", datetime(2026, 10, 1, 11, 1, tzinfo=UTC)),
    MessageRecord(3, 1, 10, 102, "다온", "롤백은 누가?", datetime(2026, 10, 1, 11, 2, tzinfo=UTC)),
]


def settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


@pytest.mark.parametrize(
    ("answer", "underline"),
    [(SHORT, "all"), (SHORT.replace("__", ""), "none")],
)
def test_engine_reports_name_underline_without_retrying(tmp_path: Path, answer, underline) -> None:
    seen: list = []

    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            seen.append([json.loads(line) for line in workspace.log_file.read_text().splitlines()])
            workspace.close()
            return f"{answer}\n\n{RATING}"

    result = asyncio.run(CodexSummaryEngine(settings(tmp_path), Runner()).summarize(ROWS))  # type: ignore[arg-type]
    assert (result.name_underline, result.topic_critique, len(seen)) == (underline, "all", 1)


def test_name_metric_is_allowlisted_and_textless(caplog) -> None:
    caplog.set_level(logging.INFO)
    for value, logged in (("all", "all"), ("partial", "partial"), ("none", "none"), ("가람", "na")):
        metrics = RequestMetrics("time")
        metrics.name_underline = value
        metrics.emit()
        assert f'"name_underline":"{logged}"' in caplog.text
    assert "가람" not in caplog.text
