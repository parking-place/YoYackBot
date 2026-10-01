"""Reject unmistakably unusable summaries without claiming to grade factuality."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
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


RATING_LABEL = "**요약창섭의 떡밥 한줄 평가** : "
_RATING_LINE = re.compile(r"^\s*(?:\*\*)?요약창섭의 떡밥 한줄 평가(?:\*\*)?\s*:\s*(.*?)\s*$")


def split_rating(text: str) -> tuple[str, str | None]:
    """Return the body and one normalized closing rating line, or None if it is not last.

    Earlier duplicate rating lines are dropped; a rating followed by other text is a format
    violation, so every rating line is removed and the caller may ask for the rating alone.
    """
    lines = text.rstrip().splitlines()
    matches = [index for index, line in enumerate(lines) if _RATING_LINE.match(line)]
    if not matches:
        return text.rstrip(), None
    last = matches[-1]
    content = _RATING_LINE.match(lines[last]).group(1)  # type: ignore[union-attr]
    trailing = [line for line in lines[last + 1:] if line.strip()]
    body = "\n".join(line for index, line in enumerate(lines) if index not in matches).rstrip()
    if trailing or not content:
        return body, None
    return body, RATING_LABEL + content


# Mocking unfinished talk (1.1.1a): channel talk keeps going, so delay is not a flaw.
ONGOING_JAB_TERMS = (
    "질질", "미루", "미뤄", "미뤘", "미룬", "제자리걸음", "헛바퀴", "흐지부지", "용두사미",
    "숙제로 남", "끝맺음", "마무리는", "결론도 없", "아무것도 안 정", "정한 게 없", "싱겁",
)


def _narration_pairs(text: str) -> list[tuple[str, str]]:
    """(raw, cleaned) narrator lines: quotes, block quotes and code may report what was said."""
    lines: list[tuple[str, str]] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(">"):
            continue
        lines.append((line, _FILLER.sub("", _QUOTED.sub("", line))))
    return lines


def _narration(text: str) -> list[str]:
    return [cleaned for _raw, cleaned in _narration_pairs(text)]


def narrator_uses_hate_term(text: str) -> bool:
    return any(term in line for line in _narration(text) for term in HATE_TERMS)


# Inside critique and rating lines these phrases mean "still not settled" is the joke (1.1.2).
CRITIQUE_JAB_TERMS = ("아직", "다음 회의", "나중에", "못 박", "미정", "안 잡", "안개 속", "감감")


def narrator_mocks_ongoing(text: str) -> bool:
    """True when narration treats unfinished, still-running talk as something to sneer at."""
    for raw, line in _narration_pairs(text):
        if any(term in line for term in ONGOING_JAB_TERMS):
            return True
        if (raw.lstrip().startswith("↳") or _RATING_LINE.match(raw)) and any(
            term in line for term in CRITIQUE_JAB_TERMS
        ):
            return True
    return False


# Pictographs, dingbats, flags, joiners, selectors and skin tones; arrows such as ↳ are kept.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF"
    "\u200D\uFE0E\uFE0F\u20E3\U000E0020-\U000E007F]"
)


def strip_emoji(text: str) -> str:
    """Remove emoji for '이모지 빼고' and tidy the spaces they leave behind."""
    lines = []
    for line in text.splitlines():
        if not _EMOJI.search(line):
            lines.append(line)
            continue
        cleaned = _EMOJI.sub("", line)
        if cleaned.lstrip().startswith("**"):
            cleaned = re.sub(r"^(\s*)\*\*\s+", r"\1**", cleaned)
        cleaned = re.sub(r"(?<=\S) {2,}", " ", cleaned).rstrip()
        if not line[:1].isspace():
            cleaned = cleaned.lstrip()
        lines.append(cleaned)
    return "\n".join(lines)


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


# A topic heading is a bold-only line, optionally bulleted, with nothing but emoji or marks after it.
_TOPIC_HEADING = re.compile(r"^\s*(?:[-*•]\s+)?\*\*([^*]+)\*\*[^\w]*$")
_GROUP_HEADINGS = frozenset({"결정 난 거", "진행 중인 거", "아직 안 정해진 거", "결정", "진행 중", "미정"})
_NOT_WORD = re.compile(r"[^\w\s]")


@dataclass(frozen=True)
class TopicSection:
    content_lines: int
    critiques: int


def topic_sections(text: str) -> list[TopicSection]:
    """Split narration into topics; decision/ongoing groups and the rating line are not topics."""
    sections: list[list[int]] = []
    current: list[int] | None = None
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        if _RATING_LINE.match(line):
            current = None
            continue
        heading = _TOPIC_HEADING.match(line)
        if heading:
            if " ".join(_NOT_WORD.sub("", heading.group(1)).split()) in _GROUP_HEADINGS:
                current = None
            else:
                current = [0, 0]
                sections.append(current)
            continue
        if current is not None:
            current[1 if stripped.startswith("↳") else 0] += 1
    return [TopicSection(content, critiques) for content, critiques in sections]


def topic_critique(text: str) -> str:
    """all/partial/none: how many topics end with a critique line; na when there are no topics."""
    sections = topic_sections(text)
    if not sections:
        return "na"
    covered = sum(section.critiques > 0 for section in sections)
    if covered == len(sections):
        return "all"
    return "none" if covered == 0 else "partial"
