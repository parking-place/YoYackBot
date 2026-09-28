"""Reject unmistakably unusable summaries without claiming to grade factuality."""

from collections.abc import Sequence
from enum import Enum


class OutputIssue(Enum):
    EMPTY = "empty"
    NON_KOREAN = "non_korean"
    SOURCE_COPY = "source_copy"
    TOOL_REPORT = "tool_report"


def inspect_output(text: str, source_bodies: Sequence[str]) -> OutputIssue | None:
    """Catch mechanical failures; a human must still review attribution and facts."""
    clean = text.strip()
    if not clean or clean == "YOYACK_INPUT_UNAVAILABLE":
        return OutputIssue.EMPTY
    if not any("가" <= character <= "힣" for character in clean):
        return OutputIssue.NON_KOREAN
    bodies = [body.strip() for body in source_bodies if body.strip()]
    if bodies and (clean in bodies or clean == "\n".join(bodies)):
        return OutputIssue.SOURCE_COPY
    if any(marker in clean for marker in (
        "/work/conversation.jsonl", "/auth/auth.json", "YOYACK_INPUT_UNAVAILABLE",
    )):
        return OutputIssue.TOOL_REPORT
    return None
