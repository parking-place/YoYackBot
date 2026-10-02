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
    NO_BODY = "no_body"


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


# A topic critique: "↳ …" or, since 1.1.2a, the blockquote form "> ↳ _…_".
_CRITIQUE = re.compile(r"^\s*(?:>\s*)?↳")


def is_critique(line: str) -> bool:
    return bool(_CRITIQUE.match(line))


def _narration_pairs(text: str) -> list[tuple[str, str]]:
    """(raw, cleaned) narrator lines: quotes and code may report what was said, critiques may not."""
    lines: list[tuple[str, str]] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or (stripped.startswith(">") and not is_critique(line)):
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
        if (is_critique(raw) or _RATING_LINE.match(raw)) and any(
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


# Speaker position: an optional heading/list marker and emoji, then the key wrapped in any
# nesting of bold, italic, underline or strikethrough (`**__P1__**`, `__**P1**__`, `*P1*`).
_SPEAKER_HEADING = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+)?(?:[-*+•][ \t]+|[0-9]+[.)][ \t]+)?"
    r"(?:[^\w\s*_~`>]+[ \t]*)?[*_~]*P[1-9][0-9]*[*_~]*"
    r"(?:[ \t]*[:：\-–—]|[은는이가](?=[ \t]))"
)
_INTERNAL_KEY = re.compile(r"(?<![A-Za-z0-9])P[1-9][0-9]*(?![0-9])")


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


def rating_issue(rating: str, source_bodies: Sequence[str]) -> OutputIssue | None:
    """The same core checks for a rating line; it names no one, so any internal key fails."""
    issue = inspect_output(rating, source_bodies)
    if issue is None and _INTERNAL_KEY.search(rating):
        return OutputIssue.SPEAKER_KEY
    return issue


_WORDS = re.compile(r"[\W_]+")


def summary_body_missing(body: str, notices: Sequence[str] = ()) -> bool:
    """True when only blank, decorative or notice lines remain once the rating is set aside."""
    skip = {_WORDS.sub("", notice) for notice in notices}
    for line in body.splitlines():
        words = _WORDS.sub("", line)
        if words and words not in skip and any("가" <= char <= "힣" for char in words):
            return False
    return True


# A topic heading is a markdown title (### …) or, as before, a bold-only line with only emoji after it.
_TOPIC_HEADING = re.compile(r"^\s*(?:#{1,3}\s+(.+?)\s*|(?:[-*•]\s+)?\*\*([^*]+)\*\*[^\w]*)$")
# Not topics: decision/ongoing groups and a bolded refusal notice.
_GROUP_HEADINGS = frozenset({
    "결정 난 거", "진행 중인 거", "아직 안 정해진 거", "결정", "진행 중", "미정",
    "추가 요청 중 일부는 들어줄 수 없었소",
})
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
            title = heading.group(1) or heading.group(2)
            if " ".join(_NOT_WORD.sub("", title).split()) in _GROUP_HEADINGS:
                current = None
            else:
                current = [0, 0]
                sections.append(current)
            continue
        if current is not None:
            current[1 if is_critique(line) else 0] += 1
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


_UNDERLINED = re.compile(r"__([^_\n]+?)__")


def name_underline(text: str, names: Sequence[str]) -> str:
    """all/partial/none: are speaker names in the body underlined? na when no name appears.

    Critique and rating lines, quotes and code are skipped; one-letter names are too short to
    tell apart from ordinary words and are not counted.
    """
    candidates = sorted({name for name in names if len(name) >= 2}, key=len, reverse=True)
    underlined = plain = 0
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or stripped.startswith(">") or is_critique(line) or _RATING_LINE.match(line):
            continue
        line = _QUOTED.sub("", re.sub(r"`[^`\n]*`", "", line))
        for match in _UNDERLINED.finditer(line):
            underlined += any(match.group(1).strip("*").startswith(name) for name in candidates)
        rest = _UNDERLINED.sub(" ", line)
        for name in candidates:
            plain += rest.count(name)
            rest = rest.replace(name, " ")
    if underlined + plain == 0:
        return "na"
    if plain == 0:
        return "all"
    return "none" if underlined == 0 else "partial"
