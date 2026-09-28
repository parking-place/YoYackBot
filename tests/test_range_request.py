"""KST calendar boundaries, frozen cutoffs, and stable message ordering."""

from datetime import UTC, datetime, timedelta

import pytest

from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RequestKind
from yoyackbot.parser import CommandLimitError
from yoyackbot.range_request import eligible_message, message_sort_key, resolve_range


SETTINGS = Settings.from_environment({"DISCORD_BOT_TOKEN": "test-token"})


@pytest.mark.parametrize(
    ("accepted", "start"),
    [
        (datetime(2026, 9, 28, 15, 0, tzinfo=UTC), datetime(2026, 9, 28, 15, 0, tzinfo=UTC)),
        (datetime(2026, 9, 30, 15, 0, 1, tzinfo=UTC), datetime(2026, 9, 30, 15, 0, tzinfo=UTC)),
        (datetime(2026, 12, 31, 15, 30, tzinfo=UTC), datetime(2026, 12, 31, 15, 0, tzinfo=UTC)),
        (datetime(2026, 12, 31, 14, 59, tzinfo=UTC), datetime(2026, 12, 30, 15, 0, tzinfo=UTC)),
    ],
)
def test_today_uses_kst_date_even_at_midnight_month_and_year_edges(
    accepted: datetime, start: datetime
) -> None:
    request = resolve_range("오늘", SETTINGS, accepted)
    assert request.kind is RequestKind.TIME
    assert request.start == start
    assert request.accepted_at == accepted


@pytest.mark.parametrize(
    ("option", "delta"),
    [
        ("", timedelta(minutes=60)),
        ("30분", timedelta(minutes=30)),
        ("2시간", timedelta(hours=2)),
        ("7일", timedelta(days=7)),
        ("4주", timedelta(weeks=4)),
    ],
)
def test_duration_is_exact_and_not_limited_by_cache_retention(option: str, delta: timedelta) -> None:
    accepted = datetime(2026, 9, 28, 20, 15, tzinfo=UTC)
    request = resolve_range(option, SETTINGS, accepted)
    assert request.start == accepted - delta
    assert request.accepted_at == accepted


def test_default_duration_obeys_configured_minutes_and_limit() -> None:
    settings = Settings.from_environment(
        {"DISCORD_BOT_TOKEN": "test-token", "YOYACK_DEFAULT_MINUTES": "45"}
    )
    accepted = datetime(2026, 9, 28, tzinfo=UTC)
    assert resolve_range("", settings, accepted).start == accepted - timedelta(minutes=45)
    invalid = Settings.from_environment(
        {"DISCORD_BOT_TOKEN": "test-token", "YOYACK_DEFAULT_MINUTES": "1441"}
    )
    with pytest.raises(CommandLimitError):
        resolve_range("", invalid, accepted)


def test_count_has_no_start_and_cutoff_does_not_move() -> None:
    accepted = datetime(2026, 9, 28, 12, tzinfo=UTC)
    request = resolve_range("100개", SETTINGS, accepted, trigger_message_id=500)
    assert request.kind is RequestKind.COUNT and request.count == 100 and request.start is None
    assert request.accepted_at == accepted and request.trigger_message_id == 500


def test_half_open_time_window_excludes_command_and_ties_sort_by_id() -> None:
    accepted = datetime(2026, 9, 28, 12, tzinfo=UTC)
    request = resolve_range("30분", SETTINGS, accepted, trigger_message_id=500)

    def record(message_id: int, when: datetime) -> MessageRecord:
        return MessageRecord(message_id, 1, 2, 3, "author", "synthetic", when)

    assert request.start is not None
    start = request.start
    candidates = [
        record(12, start),
        record(11, start),
        record(10, start - timedelta(microseconds=1)),
        record(13, accepted - timedelta(microseconds=1)),
        record(14, accepted),
        record(500, start),
    ]
    included = sorted((item for item in candidates if eligible_message(item, request)), key=message_sort_key)
    assert [item.message_id for item in included] == [11, 12, 13]
