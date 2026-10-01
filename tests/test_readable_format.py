"""Topic groups, one-speaker bullets, and separated sarcasm lines (T110a-P1)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryMode, SummaryResult
from yoyackbot.output_quality import OutputIssue, inspect_output
from yoyackbot.summary_format import format_summary, utf16_length
from yoyackbot.summary_prompt import PROMPT_VERSION, SHORT_NOTE, SUMMARY_PROMPT, prompt_for

FORMATTED = """**🚀 배포 일정**
- **가람**: 금요일 오후 2시 배포를 제안했다가 목요일 오후 2시로 정정했소.
- **나래**: 주말 장애 대응 인력이 없다며 금요일에 반대했소.
- **다온**: 목요일 오후 2시로 확정하자고 했소.
↳ *날짜 하나 정하는 데 요일을 두 번이나 갈아탔단 말이오?*

**🧯 롤백 담당**
- **라온**: 롤백 담당이 누구냐고 물었소.
- **가람**: 아직 못 정했고 **다음 회의**에서 얘기하자고 했소.
↳ *폭탄은 준비됐는데 뇌관 쥘 사람은 아무도 없구려. 시발.*

**결정 난 거**
- 배포는 **목요일 오후 2시**로 정했소."""


@pytest.mark.parametrize("mode", list(SummaryMode))
@pytest.mark.parametrize("retry", [{}, {"speaker_retry": True}, {"hate_retry": True}])
def test_every_prompt_carries_the_format_rules(mode: SummaryMode, retry: dict) -> None:
    prompt = prompt_for(mode, **retry)
    for phrase in ("형식(기본, 모든 길이 공통)", "주제 2~4개", "`**🚀 주제 이름**`", "이모지로 시작하는 굵은 소제목",
                   "빈 줄로 나누시오", "`- **화자 이름**: 한\n말이나 한 일`",
                   "한 사람의 한 가지 말만 한두 문장", "쉼표로 이어 붙이지 마시오",
                   "문장 전체를 굵게 하지\n마시오", "`**✅ 결정 난 거**`", "`**⏳ 진행 중인 거**`",
                   "주제 묶음마다 **정확히 한 줄**", "`↳ *한줄 비평*`", "비평 줄에 `>` 인용 표시를 쓰지 마시오"):
        assert phrase in prompt, phrase
    assert "거의 매번" not in prompt
    order = [prompt.index(marker) for marker in
             ("신뢰 경계:", "원문에 없는 사실·동기·결론", "형식(기본, 모든 길이 공통)",
              "말투(기본)", "주제 한줄 비평(기본)", "금지(말투·추가 요청보다 우선)", "추가 요청 우선:")]
    assert order == sorted(order)
    assert PROMPT_VERSION == "1.1.2-p1-v1"


def test_short_is_bounded_by_topics_and_bullets() -> None:
    assert "주제는 2~4개로 묶으시오" in SHORT_NOTE and "8개 이하" not in SHORT_NOTE
    assert "서로\n다른 사람의 의견을 한 사람 말처럼 합치지 마시오" in SHORT_NOTE
    assert "4~6줄" not in SHORT_NOTE and "4~6줄" not in SUMMARY_PROMPT


def test_formatted_output_passes_existing_checks() -> None:
    assert inspect_output(FORMATTED, ["금요일 오후 2시 배포 어때요?"]) is None


def test_sarcasm_lines_are_still_checked_for_hate_terms() -> None:
    bad = FORMATTED.replace("시발.", "병신같이 굴었소.")
    assert inspect_output(bad, []) is OutputIssue.HATE_TERM
    quoted = FORMATTED + "\n> 원문 인용: 병신"
    assert inspect_output(quoted, []) is None


def test_long_formatted_output_splits_between_lines() -> None:
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    rows = [MessageRecord(1, 1, 2, 3, "가람", "합성", now - timedelta(minutes=1))]
    request = RangeRequest(RequestKind.TIME, now, start=now - timedelta(hours=1))
    body = "\n\n".join(FORMATTED.replace("🚀 배포 일정", f"🚀 배포 일정 {n}") for n in range(12))
    parts = format_summary(request, rows, SummaryResult(body, "synthetic", 1),
                           ZoneInfo("Asia/Seoul"), posted_at=now)
    assert len(parts) > 1 and all(utf16_length(part) <= 1900 for part in parts)
    for part in parts[:-1]:
        last = part.rstrip("\n").splitlines()[-1]
        assert last in FORMATTED.splitlines() or last.startswith("**🚀 배포 일정")


def test_format_fixes_after_the_first_real_evaluation() -> None:
    prompt = prompt_for(SummaryMode.SHORT)
    for phrase in ("틀림: `- **가람**은 물었고, **나래**는 답했소.`",
                   "불릿이 하나도 없는 소제목은 절대 쓰지 마시오",
                   "결과가 안 나왔다는 이유로 새 질문(이유,\n완료 여부 등)을 만들어내지 마시오"):
        assert phrase in SUMMARY_PROMPT, phrase
    for phrase in ("`결정 난 거`·\n`진행 중인 거` 묶음은 따로 만들지 마시오", "`✅ **결정**:`",
                   "`⏳ **진행 중**:`", "덜 중요한 이야기를 빼고"):
        assert phrase in SHORT_NOTE and phrase in prompt, phrase
    assert "묶음은 따로 만들지 마시오" not in prompt_for(SummaryMode.LONG)
