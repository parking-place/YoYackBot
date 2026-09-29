"""Reject unmistakably unusable summaries without claiming to grade factuality."""

import re
from collections.abc import Sequence
from enum import Enum


class OutputIssue(Enum):
    EMPTY = "empty"
    NON_KOREAN = "non_korean"
    SOURCE_COPY = "source_copy"
    TOOL_REPORT = "tool_report"
    SPEAKER_KEY = "speaker_key"


_SPEAKER_HEADING = re.compile(
    r"^[ \t]*(?:[-*•][ \t]+|[0-9]+[.)][ \t]+)?(?:\*\*|__)?P[1-9][0-9]*"
    r"(?:\*\*|__)?(?:[ \t]*[:：-]|[은는이가](?=[ \t]))"
)


def uses_internal_speaker_as_attribution(text: str) -> bool:
    """Catch internal keys in speaker-heading position, never rewrite quoted or code text."""
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(">"):
            continue
        if _SPEAKER_HEADING.match(line):
            return True
    return False


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
    if uses_internal_speaker_as_attribution(clean):
        return OutputIssue.SPEAKER_KEY
    return None
