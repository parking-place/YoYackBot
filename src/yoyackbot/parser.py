"""Included trigger detection and help routing, before range parsing."""

import re
from dataclasses import dataclass
from enum import Enum

from yoyackbot.config import Settings
from yoyackbot.domain import SummaryMode

TRIGGER = "!!요약좀"
USAGE_WORD = "사용량"
STATUS_WORD = "상태"
CHANNELS_WORD = "채널"
HELP_WORD = re.compile(r"(?<!\S)도움(?:말)?(?=\s|$)")

# The user's short help text (1.1.2a). "  " before a newline is a Discord line break; the day
# limit comes from settings and the 2-day example is hidden when the limit is shorter.
_HELP_LINES = (
    "📜 **요약 사용법**",
    "",
    "`!!요약좀` → 최근 1시간  ",
    "`3` → 3시간 / `30분` `2시간` `100개` `오늘`{two_days} `1주` `{max_days}일` 지원  ",
    "※ 숫자만 쓰면 시간, 최대 {max_days}일",
    "",
    "🔍 `길게` → 흐름·결정 포함  ",
    "🔎 `자세히` → 가장 상세  ",
    "✏️ 뒤에 요청 추가 가능: `시간순으로`, `욕 빼고`, `평가 빼줘` 등  ",
    "※ 추가 요청 200자, 범위 변경·허위 생성 불가",
    "",
    "⚙️ `사용량` → Codex 한도  ",
    "📊 `상태` → 채널·캐시·DB·마지막 요약  ",
    "📡 `채널` → 주시 채널(DM)",
    "",
    "진행 중엔 현재 범위, 수집 중엔 준비 중이라고 답하오.  ",
    "주시 채널은 `/채널 설정`에서 정하시오.  ",
    "봇 관리 역할은 `/관리권한 설정`에서 정하시오.",
)
HELP_TEMPLATE = "\n".join(_HELP_LINES)


def help_text(settings: Settings | None = None) -> str:
    """The short help with the effective day limit, never advertising a rejected example."""
    days = 30 if settings is None else settings.max_days
    return HELP_TEMPLATE.format(two_days=" `2일`" if days >= 2 else "", max_days=days)


HELP_TEXT = help_text()


class RouteKind(Enum):
    NONE = "none"
    HELP = "help"
    SUMMARY = "summary"
    USAGE = "usage"
    STATUS = "status"
    CHANNELS = "channels"


@dataclass(frozen=True)
class TriggerRoute:
    kind: RouteKind
    options: str = ""
    repeated: bool = False


class OptionKind(Enum):
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"
    WEEKS = "weeks"
    COUNT = "count"
    TODAY = "today"


@dataclass(frozen=True)
class ParsedOption:
    kind: OptionKind
    value: int | None
    explicit: bool = True


class CommandSyntaxError(ValueError):
    """An option cannot be interpreted without guessing a range."""


class CommandLimitError(ValueError):
    """A syntactically valid option exceeds the configured range."""


USAGE_NOTICE = "🤔 그 명은 알아듣기 어렵소. `!!요약좀 도움`에서 사용법을 살펴보시오. 📜"
POLITE_ENDINGS = ("부탁하오", "부탁해요", "해주세요")
OPTION_PATTERN = re.compile(r"([0-9]+)\s*(개|분|시간|일|주)?\Z")
UNIT_KIND = {
    "개": OptionKind.COUNT,
    "분": OptionKind.MINUTES,
    "시간": OptionKind.HOURS,
    "일": OptionKind.DAYS,
    "주": OptionKind.WEEKS,
}


def route_trigger(content: str) -> TriggerRoute:
    """Use the first trigger's options; help has priority across repeated triggers."""
    _, marker, after = content.partition(TRIGGER)
    if not marker:
        return TriggerRoute(RouteKind.NONE)
    repeated = TRIGGER in after
    options = after.partition(TRIGGER)[0].strip()
    if HELP_WORD.search(after):
        return TriggerRoute(RouteKind.HELP, repeated=repeated)
    if options == USAGE_WORD:
        return TriggerRoute(RouteKind.USAGE, repeated=repeated)
    if options == STATUS_WORD:
        return TriggerRoute(RouteKind.STATUS, repeated=repeated)
    if options == CHANNELS_WORD:
        return TriggerRoute(RouteKind.CHANNELS, repeated=repeated)
    return TriggerRoute(RouteKind.SUMMARY, options=options, repeated=repeated)


MODE_WORDS = {"짧게": SummaryMode.SHORT, "길게": SummaryMode.LONG, "자세히": SummaryMode.DETAILED}
RESERVED_WORDS = (USAGE_WORD, STATUS_WORD, CHANNELS_WORD)
MAX_REQUEST_NOTE = 200
REQUEST_TOO_LONG_NOTICE = f"✂️ 추가 요청은 {MAX_REQUEST_NOTE}자까지만 알아듣겠소. 📏"
_RANGE_UNITS = {"개", "분", "시간", "일", "주"}
_MENTION = re.compile(r"<@[!&]?\d+>|<#\d+>|@everyone|@here")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u2028\u2029\ufeff]")


@dataclass(frozen=True)
class SummaryCommand:
    """`[range] [length] [request note...]`, read in that order only."""

    range_text: str
    mode: SummaryMode
    note: str | None


def _looks_like_range(text: str) -> bool:
    try:
        parse_option(text)
    except CommandSyntaxError:
        return False
    return bool(text.strip())


def clean_request_note(text: str) -> str | None:
    """Drop mentions and control characters, collapse spaces; empty means no request."""
    cleaned = " ".join(_CONTROL.sub(" ", _MENTION.sub(" ", text)).split())
    if not cleaned or cleaned in POLITE_ENDINGS:
        return None
    if len(cleaned) > MAX_REQUEST_NOTE:
        raise CommandLimitError(REQUEST_TOO_LONG_NOTICE)
    return cleaned


_NO_RATING = re.compile(
    r"평가\S{0,2}\s*(?:좀\s*|는\s*|도\s*)?(?:빼|없이|생략|지워|지우|말고|안\s*해|하지\s*마)"
)
_KEEP_RATING = re.compile(r"빼지\s*말|지우지\s*말|생략하지\s*말")
_NO_EMOJI = re.compile(
    r"(?:이모지|이모티콘|emoji)\S{0,2}\s*(?:좀\s*|는\s*|도\s*)?"
    r"(?:빼|없이|생략|지워|지우|말고|안\s*(?:써|쓰|해)|쓰지\s*마|금지)",
    re.IGNORECASE,
)


_UNSAFE_REQUEST = re.compile(
    r"지시문|프롬프트|시스템|규칙\S{0,2}\s*(?:무시|해제|없애|끝)|무시하고|무시해|"
    r"\d+\s*일\s*(?:전체|치\s*(?:전부|다|모두))|전체\s*(?:기간|대화)|다른\s*채널|모든\s*채널|"
    r"했다고\s*(?:써|적어|해)|라고\s*(?:써|적어)|화자\S{0,2}.{0,12}바꿔|"
    r"비하어|병신|성적으로|야하게|auth|파일|https?://|URL|도구|«|»|"
    r"신뢰\s*경계|인용이\s*끝|system|[{}<>]",
    re.IGNORECASE,
)


def wants_refusal_notice(note: str) -> bool:
    """Obvious out-of-bounds requests always get the refusal line, even if the model forgets."""
    return bool(_UNSAFE_REQUEST.search(note))


def wants_no_rating(note: str) -> bool:
    """A request that explicitly drops the closing rating, decided in code not by the model."""
    return bool(_NO_RATING.search(note)) and not _KEEP_RATING.search(note)


def wants_no_emoji(note: str) -> bool:
    return bool(_NO_EMOJI.search(note)) and not _KEEP_RATING.search(note)


def parse_summary_command(options: str) -> SummaryCommand:
    """Never reorder parts: a request that looks like a range, length, or command is refused."""
    words = options.split()
    range_text = ""
    for size in (2, 1):
        if len(words) >= size and (size == 1 or words[1] in _RANGE_UNITS):
            candidate = " ".join(words[:size])
            if _looks_like_range(candidate):
                range_text, words = candidate, words[size:]
                break
    mode = SummaryMode.SHORT
    if words and words[0] in MODE_WORDS:
        mode = MODE_WORDS[words.pop(0)]
    if words:
        first = words[0]
        if (
            _looks_like_range(first)
            or first[:1].isdigit()
            or (len(words) > 1 and words[1] in _RANGE_UNITS and _looks_like_range(" ".join(words[:2])))
            or any(word.startswith(tuple(MODE_WORDS)) for word in words)
            or first.startswith(RESERVED_WORDS)
        ):
            raise CommandSyntaxError(USAGE_NOTICE)
    return SummaryCommand(range_text, mode, clean_request_note(" ".join(words)))


def parse_option(options: str) -> ParsedOption:
    """Parse one range option without applying configurable numeric limits."""
    text = options.strip()
    if not text:
        return ParsedOption(OptionKind.HOURS, 1, explicit=False)
    for ending in POLITE_ENDINGS:
        if text.endswith(" " + ending):
            text = text[: -len(ending)].strip()
            break
    if text == "오늘":
        return ParsedOption(OptionKind.TODAY, None)
    match = OPTION_PATTERN.fullmatch(text)
    if match is None or len(match.group(1)) > 20:
        raise CommandSyntaxError(USAGE_NOTICE)
    value = int(match.group(1))
    kind = UNIT_KIND.get(match.group(2), OptionKind.HOURS)
    return ParsedOption(kind, value)


def validate_option(option: ParsedOption, settings: Settings) -> ParsedOption:
    """Reject nonpositive and over-limit requests before any costly work begins."""
    if option.kind is OptionKind.TODAY:
        return option
    limits = {
        OptionKind.MINUTES: (settings.max_minutes, "분"),
        OptionKind.HOURS: (settings.max_hours, "시간"),
        OptionKind.DAYS: (settings.max_days, "일"),
        OptionKind.WEEKS: (settings.max_weeks, "주"),
        OptionKind.COUNT: (settings.max_messages, "개"),
    }
    maximum, unit = limits[option.kind]
    if option.value is None or not 1 <= option.value <= maximum:
        raise CommandLimitError(
            f"📏 {unit} 단위는 1부터 {maximum}까지 고르시오. `!!요약좀 도움`에서 사용법을 살펴보시오. 📜"
        )
    return option
