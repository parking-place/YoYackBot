"""Included trigger detection and help routing, before range parsing."""

import re
from dataclasses import dataclass
from enum import Enum

from yoyackbot.config import Settings
from yoyackbot.domain import SummaryMode

TRIGGER = "!!요약좀"
USAGE_WORD = "사용량"
HELP_WORD = re.compile(r"(?<!\S)도움(?:말)?(?=\s|$)")

HELP_TEMPLATE = """📜 요약 사용법을 알려드리겠소.

`!!요약좀` — 최근 1시간의 대화를 요약하오.
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
    return TriggerRoute(RouteKind.SUMMARY, options=options, repeated=repeated)


MODE_WORDS = {"자세히": SummaryMode.DETAILED, "짧게": SummaryMode.SHORT}


def _without_polite_ending(text: str) -> str:
    for ending in POLITE_ENDINGS:
        if text == ending:
            return ""
        if text.endswith(" " + ending):
            return text[: -len(ending)].strip()
    return text


def split_mode(options: str) -> tuple[str, SummaryMode]:
    """Accept one density word only after the range; never reorder or merge modes."""
    words = _without_polite_ending(options.strip()).split()
    mode = SummaryMode.NORMAL
    if words and words[-1] in MODE_WORDS:
        mode = MODE_WORDS[words.pop()]
    if any(word in MODE_WORDS for word in words):
        raise CommandSyntaxError(USAGE_NOTICE)
    return " ".join(words), mode


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
