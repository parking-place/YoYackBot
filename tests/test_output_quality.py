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
])
def test_inspect_output(summary: str, bodies: list[str], expected: OutputIssue | None) -> None:
    assert inspect_output(summary, bodies) is expected
