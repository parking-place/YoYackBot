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

HELP_TEMPLATE = """📜 요약 사용법을 알려드리겠소.

`!!요약좀` — 최근 1시간의 대화를 주제별로 짧게 요약하오.
`!!요약좀 3` — 최근 3시간의 대화를 요약하오.
`!!요약좀 30분` — 최근 30분의 대화를 요약하오.
`!!요약좀 2시간` — 최근 2시간의 대화를 요약하오.
`!!요약좀 100개` — 최근 일반 사용자 메시지 100개를 요약하오.
`!!요약좀 오늘` — 오늘 00시부터 지금까지의 대화를 요약하오.
`!!요약좀 {example_days}일` — 최근 {example_days}일간의 대화를 요약하오.
`!!요약좀 {max_days}일` — 최근 {max_days}일간의 대화를 요약하오.
`!!요약좀 1주` — 최근 1주간의 대화를 요약하오.

숫자만 적으면 시간 단위로 알아듣겠소.
{limit_notice}

기본은 짧게 요약하오. 범위 뒤에 길이를 한 번 붙이면 같은 범위를 더 길게 요약하오. 범위를 생략하면 최근 1시간이오.
`!!요약좀 [범위] 길게` — 화자별 흐름과 결정·남은 점까지 요약하오. 예: `!!요약좀 오늘 길게`
`!!요약좀 [범위] 자세히` — 아주 길고 촘촘하게 요약하오. 예: `!!요약좀 3일 자세히`
`짧게`를 붙여도 기본과 같소. 모든 요약 끝에는 **요약창섭의 떡밥 한줄 평가**가 붙소.

범위·길이 뒤에 하고 싶은 말을 적으면 요약할 때 참고하오. 예: `!!요약좀 2분 길게 시간순으로 해줘`
(추가 요청은 200자까지이며, 범위를 바꾸거나 없는 사실을 만들어 달라는 말은 듣지 않소.)

`!!요약좀 사용량` — 요약봇 Codex 계정의 남은 한도를 알려주오.
`!!요약좀 상태` — 이 서버의 주시 채널·캐시 건수·DB 크기(모든 서버가 함께 쓰는 파일)·마지막 요약을 알려주오.
`!!요약좀 채널` — 이 서버에서 봇이 살피고 있는 채널 가운데 그대에게 보이는 채널을 알려주오.
사용량·상태·채널은 주시 채널에서만 답하며, 요약이 아니므로 대기 시간을 쓰지 않소.

요약을 시작하면 범위를 먼저 알려주고, 요약 중에 다시 부르면 진행 중인 범위를 알려주오.
채널이 처음 대화를 모으거나 빠진 대화를 확인하는 동안에는 준비 중이라고 답하오.
주시할 채널은 관리자가 `/채널 설정`에서 정하시오."""


def help_text(settings: Settings | None = None) -> str:
    """Explain the effective day limit without advertising a rejected example."""
    days = 30 if settings is None else settings.max_days
    notice = (
        "기간 요약은 최대 30일까지 가능하오." if days == 30
        else f"일 단위 요청은 최대 {days}일까지 가능하오."
    )
    return HELP_TEMPLATE.format(
        example_days=min(days, 2), max_days=days, limit_notice=notice
    )


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


USAGE_NOTICE = "그 명은 알아듣기 어렵소. `!!요약좀 도움`에서 사용법을 살펴보시오."
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
REQUEST_TOO_LONG_NOTICE = f"추가 요청은 {MAX_REQUEST_NOTE}자까지만 알아듣겠소."
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
            f"{unit} 단위는 1부터 {maximum}까지 고르시오. `!!요약좀 도움`에서 사용법을 살펴보시오."
        )
    return option
