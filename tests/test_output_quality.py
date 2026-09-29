"""Mechanical summary-output failure categories."""

import pytest

from yoyackbot.output_quality import OutputIssue, inspect_output


@pytest.mark.parametrize(("summary", "bodies", "expected"), [
    ("  ", ["회의해요"], OutputIssue.EMPTY),
    ("YOYACK_INPUT_UNAVAILABLE", ["회의해요"], OutputIssue.EMPTY),
    ("Here is the summary.", ["회의해요"], OutputIssue.NON_KOREAN),
    ("회의해요", ["회의해요"], OutputIssue.SOURCE_COPY),
    ("회의해요\n좋아요", ["회의해요", "좋아요"], OutputIssue.SOURCE_COPY),
    ("/work/conversation.jsonl을 읽었소.", ["회의해요"], OutputIssue.TOOL_REPORT),
    ("인증 정보를 /auth/auth.json에서 봤소.", ["회의해요"], OutputIssue.TOOL_REPORT),
    ("가람이 회의를 제안하고 나래가 동의했소.", ["회의해요", "좋아요"], None),
    ("- **P1**: 회의를 제안했소.", ["회의해요"], OutputIssue.SPEAKER_KEY),
    ("P2는 일정을 검토하겠다고 했소.", ["검토해요"], OutputIssue.SPEAKER_KEY),
    ("'P1'이라는 표기를 논의했소.", ["표기 논의"], None),
    ("P1이라는 약어를 설명했소.", ["약어 설명"], None),
    ("> P1: 인용문\n가람이 회의를 제안했소.", ["회의해요"], None),
    ("```\nP1: 예시\n```\n가람이 설명했소.", ["설명해요"], None),
])
def test_inspect_output(summary: str, bodies: list[str], expected: OutputIssue | None) -> None:
    assert inspect_output(summary, bodies) is expected
