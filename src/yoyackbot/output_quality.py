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
    HATE_TERM = "hate_term"


# Group-targeted slurs only. Ordinary profanity (존나, 시발, 좆, 개판) is allowed by 1.0.2c.
# Words with common innocent meanings (e.g. a fish or a district) are left out to avoid
# retries that spend the account limit on false positives.
HATE_TERMS = (
    "병신", "븅신", "빙신", "ㅂㅅ", "ㅄ", "정박아", "애자새끼", "장애인새끼",
    "김치녀", "된장녀", "보슬아치", "한남충", "맘충", "틀딱",
    "짱깨", "쪽바리", "깜둥이", "똥남아", "전라디언", "개쌍도",
    "똥꼬충", "호모새끼", "개독",
)
_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|「[^」\n]*」')
_FILLER = re.compile(r"[^\w\s]|[\d_]|[\u200b-\u200d\ufeff]")


def narrator_uses_hate_term(text: str) -> bool:
    """Look only at narration: quoted source words and block quotes may be reported as said."""
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(">"):
            continue
        narration = _FILLER.sub("", _QUOTED.sub("", line))
        if any(term in narration for term in HATE_TERMS):
            return True
    return False


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
    if narrator_uses_hate_term(clean):
        return OutputIssue.HATE_TERM
    if uses_internal_speaker_as_attribution(clean):
        return OutputIssue.SPEAKER_KEY
    return None
