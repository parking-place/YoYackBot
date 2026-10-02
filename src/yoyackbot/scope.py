"""Fixed display labels for a validated request range and its start/busy notices."""

from dataclasses import dataclass

from yoyackbot.config import Settings
from yoyackbot.domain import SummaryMode
from yoyackbot.parser import OptionKind, parse_option, validate_option

BUSY_SECOND_LINE = "🧘 참을성을 가져보시오. 🙏"
MODE_WORDS = {SummaryMode.SHORT: "", SummaryMode.LONG: "길게 ", SummaryMode.DETAILED: "자세히 "}
UNITS = {
    OptionKind.MINUTES: "분", OptionKind.HOURS: "시간",
    OptionKind.DAYS: "일", OptionKind.WEEKS: "주",
}


@dataclass(frozen=True)
class RangeScope:
    """Only validated numbers and fixed words; never text copied from Discord."""

    kind: OptionKind
    value: int | None = None
    # A reply anchor wins over a range written with it (1.3.0); the notice says so.
    ignored_range: bool = False

    def __post_init__(self) -> None:
        if (self.kind in (OptionKind.TODAY, OptionKind.REPLY)) != (self.value is None):
            raise ValueError("Only today and reply ranges have no numeric value")
        if self.ignored_range and self.kind is not OptionKind.REPLY:
            raise ValueError("Only a reply range can ignore a written range")
        if self.value is not None and self.value < 1:
            raise ValueError("Scope value must be positive")

    @property
    def text(self) -> str:
        if self.kind is OptionKind.TODAY:
            return "오늘"
        if self.kind is OptionKind.REPLY:
            return "답장한 메시지부터"
        if self.kind is OptionKind.COUNT:
            return f"최근 {self.value}개"
        return f"{self.value}{UNITS[self.kind]}"


def describe_range(range_text: str, settings: Settings) -> RangeScope:
    """Label the range exactly as requested; the default uses the configured minutes."""
    option = parse_option(range_text)
    if not option.explicit:
        minutes = settings.default_minutes
        if minutes % 60 == 0:
            return RangeScope(OptionKind.HOURS, minutes // 60)
        return RangeScope(OptionKind.MINUTES, minutes)
    option = validate_option(option, settings)
    return RangeScope(option.kind, option.value)


REPLY_IGNORED_LINE = "↩️ 답장한 메시지 기준으로 요약하오(기간·개수는 무시했소)."


def start_notice(scope: RangeScope, mode: SummaryMode) -> str:
    notice = f"📝 {scope.text} 채팅을 {MODE_WORDS[mode]}요약해보겠소. ✍️"
    return f"{notice}\n{REPLY_IGNORED_LINE}" if scope.ignored_range else notice


def busy_notice(scope: RangeScope, mode: SummaryMode) -> str:
    if scope.kind is OptionKind.MINUTES:
        subject = f"{scope.text}간의"
    elif scope.kind in (OptionKind.HOURS, OptionKind.DAYS, OptionKind.WEEKS):
        subject = f"{scope.text} 분"
    else:
        subject = scope.text
    return f"⏳ 현재 {subject} 채팅을 {MODE_WORDS[mode]}요약중이오. 🔄\n{BUSY_SECOND_LINE}"
