"""Freeze a parsed command into an absolute request with a half-open end."""

from datetime import UTC, datetime, timedelta

from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind
from yoyackbot.parser import OptionKind, ParsedOption, parse_option, validate_option


def resolve_range(
    options: str,
    settings: Settings,
    accepted_at: datetime,
    *,
    trigger_message_id: int | None = None,
) -> RangeRequest:
    """Interpret and validate one command against the time it was accepted."""
    if accepted_at.tzinfo is None:
        raise ValueError("accepted_at must have a timezone")
    end = accepted_at.astimezone(UTC)
    option = parse_option(options)
    if not option.explicit:
        option = ParsedOption(OptionKind.MINUTES, settings.default_minutes, explicit=False)
    option = validate_option(option, settings)
    if option.kind is OptionKind.COUNT:
        return RangeRequest(
            RequestKind.COUNT, end, count=option.value, trigger_message_id=trigger_message_id
        )
    if option.kind is OptionKind.TODAY:
        local = end.astimezone(settings.timezone)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
            UTC
        )
    else:
        assert option.value is not None
        unit = {
            OptionKind.MINUTES: "minutes",
            OptionKind.HOURS: "hours",
            OptionKind.DAYS: "days",
            OptionKind.WEEKS: "weeks",
        }[option.kind]
        start = end - timedelta(**{unit: option.value})
    return RangeRequest(RequestKind.TIME, end, start=start, trigger_message_id=trigger_message_id)


def eligible_message(record: MessageRecord, request: RangeRequest) -> bool:
    """Exclude the command itself and the frozen end; include the start for time ranges."""
    if request.trigger_message_id == record.message_id or record.created_at >= request.accepted_at:
        return False
    return request.start is None or request.start <= record.created_at


def message_sort_key(record: MessageRecord) -> tuple[datetime, int]:
    """Give messages with identical timestamps a stable Discord snowflake order."""
    return record.created_at, record.message_id
