"""Per-topic critique metric and emoji-safe message splitting (T112-P2)."""

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
    narrator_mocks_ongoing,
    narrator_uses_hate_term,
    topic_critique,
    topic_sections,
)
from yoyackbot.summary_format import format_summary, split_body, utf16_length

RATING = f"{RATING_LABEL}달력 한 장에 요란 떨 일이오? 🔥"
SHORT = """**🚀 배포 날짜** 🗓️
금요일 안이 막히자 가람이 목요일 오후 2시로 바로잡았소. ✅ **결정**: 목요일 오후 2시 🎉
↳ *요일 하나에 판을 한 바퀴 돌렸구려* 🙄

**🧯 롤백 담당**
라온이 담당을 물었고 다음 회의에서 정하자고 했소. ⏳ **진행 중**: 롤백 담당
↳ *롤백 소리만 나와도 등골이 서늘한 모양이오* 🥶"""
LONG = """**🚀 배포 날짜**
- **가람**: 금요일 오후 2시를 제안했소.
- **나래**: 반대했소.
- **가람**: 목요일로 정정했소.
↳ *요일 퀴즈였소* 🤡

**🧯 롤백 담당**
- **라온**: 담당을 물었소.
↳ *다들 눈치만 보는구려* 👀

**✅ 결정 난 거**
- 목요일 오후 2시 배포.

**⏳ 진행 중인 거**
- 롤백 담당."""
CHRONO = "- **가람**: 금요일을 제안했소.\n- **나래**: 반대했소."


@pytest.mark.parametrize(
    ("text", "expected", "sections"),
    [
        (f"{SHORT}\n\n{RATING}", "all", [TopicSection(1, 1), TopicSection(1, 1)]),
        (f"{LONG}\n\n{RATING}", "all", [TopicSection(3, 1), TopicSection(1, 1)]),
        (CHRONO, "na", []),
        (f"{CHRONO}\n\n{RATING}", "na", []),
        (SHORT.replace("↳ *롤백 소리만 나와도 등골이 서늘한 모양이오* 🥶", ""), "partial",
         [TopicSection(1, 1), TopicSection(1, 0)]),
        ("\n".join(line for line in SHORT.splitlines() if not line.startswith("↳")), "none",
         [TopicSection(1, 0), TopicSection(1, 0)]),
        (f"```\n**가짜 소제목**\n```\n{SHORT}", "all", [TopicSection(1, 1), TopicSection(1, 1)]),
        ("- **강릉 여행** 🌊\n  - **보람**: 가자고 했소.\n  ↳ *바다 냄새부터 풍기는구려*", "all",
         [TopicSection(1, 1)]),
        ("**결정 난 거**\n- 목요일.\n\n**아직 안 정해진 거**\n- 담당.", "na", []),
        (f"{SHORT}\n\n**⏳ 진행 중**\n- 롤백 담당.\n\n**✅ 결정**\n- 목요일.", "all",
         [TopicSection(1, 1), TopicSection(1, 1)]),
        ("**📣 업데이트 안내는 아직 진행 중**\n안내 여부를 내일 보기로 했소.\n↳ *문구만 바쁘구려*", "all",
         [TopicSection(1, 1)]),
    ],
)
def test_topic_critique_counts_topics_not_groups(text, expected, sections) -> None:
    assert topic_sections(text) == sections
    assert topic_critique(text) == expected


def test_speaker_bullets_are_not_headings() -> None:
    assert topic_sections("- **가람**: 말했소.\n- **나래**: 답했소.") == []


def settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


ROWS = [MessageRecord(1, 1, 10, 100, "가람", "금요일 배포 어때요?", datetime(2026, 10, 1, 12, tzinfo=UTC))]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [(f"{SHORT}\n\n{RATING}", "all"), (f"{CHRONO}\n\n{RATING}", "na"),
     (SHORT.replace("↳ *롤백 소리만 나와도 등골이 서늘한 모양이오* 🥶", "") + f"\n\n{RATING}", "partial")],
)
def test_engine_reports_topic_critique_without_retrying(tmp_path: Path, answer, expected) -> None:
    seen: list = []

    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            seen.append([json.loads(line) for line in workspace.log_file.read_text().splitlines()])
            workspace.close()
            return answer

    engine = CodexSummaryEngine(settings(tmp_path), Runner())  # type: ignore[arg-type]
    result = asyncio.run(engine.summarize(ROWS))
    assert result.topic_critique == expected and len(seen) == 1


def test_metric_is_allowlisted_and_textless(caplog) -> None:
    caplog.set_level(logging.INFO)
    for value, logged in (("all", "all"), ("partial", "partial"), ("none", "none"), ("x", "na")):
        metrics = RequestMetrics("time")
        metrics.topic_critique = value
        metrics.emit()
        assert f'"topic_critique":"{logged}"' in caplog.text
    assert "롤백" not in caplog.text


EMOJI = ["🚀", "👨‍👩‍👧‍👦", "👍🏽", "❤️", "🏳️‍🌈", "1️⃣", "🏴󠁧󠁢󠁳󠁣󠁴󠁿"]


def test_emoji_heavy_summary_splits_on_lines_within_the_limit() -> None:
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    request = RangeRequest(RequestKind.TIME, now, start=now - timedelta(hours=1))
    topics = []
    for n in range(25):
        topics.append(f"**{EMOJI[n % 7]} 주제 {n}** {''.join(EMOJI)}\n"
                      f"{'가' * 60}소. ✅ **결정**: 목요일 {''.join(EMOJI)} <@123> @everyone\n"
                      f"↳ *요란하오* {''.join(EMOJI)}")
    text = "\n\n".join(topics) + f"\n\n{RATING}"
    parts = format_summary(request, ROWS, SummaryResult(text, "synthetic", 1),
                           ZoneInfo("Asia/Seoul"), posted_at=now)
    assert len(parts) > 1 and all(utf16_length(part) <= 1900 for part in parts)
    assert parts[-1].rstrip().endswith(RATING)
    assert not any("<@123>" in part or "@everyone" in part for part in parts)
    body = "".join(part.split("\n", 1)[1] if index else part for index, part in enumerate(parts))
    for emoji in EMOJI:
        assert body.count(emoji) >= 25 * 3


@pytest.mark.parametrize("emoji", EMOJI)
def test_hard_cuts_never_split_an_emoji_sequence(emoji: str) -> None:
    text = emoji * 400
    for budget in (17, 50, 101):
        chunks = split_body(text, budget)
        assert "".join(chunks) == text
        assert all(chunk.count(emoji) * len(emoji) == len(chunk) for chunk in chunks), (emoji, budget)
        assert all(utf16_length(chunk) <= budget for chunk in chunks)


def test_emoji_do_not_hide_or_invent_jabs() -> None:
    assert narrator_mocks_ongoing("↳ *또 질질 🐌 끄는구려* 🙄")
    assert not narrator_mocks_ongoing("⏳ **진행 중**: 롤백 담당 🕐")
    assert narrator_uses_hate_term("↳ *병신 🤡 같은 소리였소*")
    assert not narrator_uses_hate_term("↳ *요란하오* 🤡🔥")


def test_engine_strips_emoji_when_asked(tmp_path: Path) -> None:
    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            workspace.close()
            return f"{SHORT}\n\n{RATING}"

    engine = CodexSummaryEngine(settings(tmp_path), Runner())  # type: ignore[arg-type]
    plain = asyncio.run(engine.summarize(ROWS, request_note="이모지 빼고"))
    kept = asyncio.run(engine.summarize(ROWS, request_note="시간순으로 해줘"))
    assert "✅" not in plain.text and "⏳" not in plain.text and "🚀" not in plain.text
    assert plain.text.startswith("**배포 날짜**\n") and "**결정**: 목요일 오후 2시" in plain.text
    assert plain.topic_critique == "all" and plain.rating == "present"
    assert kept.text == f"{SHORT}\n\n{RATING}"
