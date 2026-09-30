"""Length notes, the snarkier tone, and long detailed output delivery (T110-P3)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryMode, SummaryResult
from yoyackbot.output_quality import OutputIssue, inspect_output
from yoyackbot.summary_format import format_summary, utf16_length
from yoyackbot.summary_prompt import (
    DETAILED_NOTE,
    HATE_RETRY_NOTE,
    PROMPT_VERSION,
    SHORT_NOTE,
    SPEAKER_RETRY_NOTE,
    SUMMARY_PROMPT,
    prompt_for,
)

ORDER = ["신뢰 경계:", "원문에 없는 사실·동기·결론", "추가 요청:", "말투(반드시 적용)",
         "금지(말투보다 우선)"]


@pytest.mark.parametrize("mode", list(SummaryMode))
@pytest.mark.parametrize("retry", [{}, {"speaker_retry": True}, {"hate_retry": True}])
def test_prompt_order_and_length_notes(mode: SummaryMode, retry: dict) -> None:
    prompt = prompt_for(mode, **retry)
    positions = [prompt.index(marker) for marker in ORDER]
    assert positions == sorted(positions)
    length_note = {SummaryMode.SHORT: SHORT_NOTE, SummaryMode.LONG: "",
                   SummaryMode.DETAILED: DETAILED_NOTE}[mode]
    assert prompt.startswith(SUMMARY_PROMPT + length_note)
    if length_note:
        assert prompt.index(length_note) > positions[-1]
    assert (SPEAKER_RETRY_NOTE in prompt) is bool(retry.get("speaker_retry"))
    assert (HATE_RETRY_NOTE in prompt) is bool(retry.get("hate_retry"))
    assert PROMPT_VERSION == "1.1.0a-p2-v2"


def test_each_length_has_its_own_instruction() -> None:
    assert "8개 이하" in SHORT_NOTE and "주제는 2~4개" in SHORT_NOTE
    for phrase in ("아주 길게", "빠짐없이", "시간 순서", "누가 누구 말에 어떻게 반응했는지",
                   "요점을 합쳐 줄이지 말고", "원문에 없는 사실·이견·해결책을\n보태지 마시오"):
        assert phrase in DETAILED_NOTE
    assert "8개 이하" not in DETAILED_NOTE and "불릿 수에 제한은 없소" in DETAILED_NOTE


def test_snark_is_aimed_at_actions_and_keeps_haoche() -> None:
    for phrase in ("띠껍고\n싸가지없는 태도", "비꼬고 빈정거리시오", "뭐 대단한 결정이라도 난 줄 알았소?",
                   "깔보는 태도", "하오체", "반말 어미로 문장을 끝내지 마시오",
                   "비아냥 형식(반드시 지키시오)", "내용은 가져오지 말고 형식만 따르시오",
                   "비아냥이 사실을 바꾸거나 없는 사실을 보태면 안 되고",
                   "주어(이름)를 분명히", "비꼬려고 새 미해결점을\n만들지 마시오",
                   "비꼼도\n행동·말·결과만 대상으로 하고 외모·지능 같은 인신공격으로 넘어가지 마시오"):
        assert phrase in SUMMARY_PROMPT, phrase


def test_snarky_profanity_is_not_a_hate_retry() -> None:
    text = "뭐 대단한 결정이라도 난 줄 알았소? 시발, 역시나 존나 아무것도 안 정했단 말이오!"
    assert inspect_output(text, []) is None
    assert inspect_output("가람이 병신같이 굴었소.", []) is OutputIssue.HATE_TERM


def test_long_detailed_output_splits_in_order_without_mentions() -> None:
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    rows = [MessageRecord(1, 1, 2, 3, "가람", "합성", now - timedelta(minutes=1))]
    request = RangeRequest(RequestKind.TIME, now, start=now - timedelta(hours=1))
    lines = [f"{index:03d}번째 줄이오. <@123> @everyone 뭐 대단한 결정이라도 난 줄 알았소?"
             for index in range(200)]
    parts = format_summary(request, rows, SummaryResult("\n".join(lines), "synthetic", 1),
                           ZoneInfo("Asia/Seoul"), posted_at=now)
    assert len(parts) > 3 and all(utf16_length(part) <= 1900 for part in parts)
    joined = "\n".join(parts)
    assert joined.index("000번째") < joined.index("199번째")
    assert "<@123>" not in joined and "@everyone" not in joined.replace("@\u200beveryone", "")
