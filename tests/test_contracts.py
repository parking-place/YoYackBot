"""Cross-layer contracts and secret-safe error behavior."""

from datetime import UTC, datetime, timedelta

import pytest

from yoyackbot.config import ConfigurationError, Settings
from yoyackbot.domain import (
    CoverageInterval,
    MessageRecord,
    RangeRequest,
    RequestKind,
    SummaryRequest,
    SummaryResult,
)
from yoyackbot.errors import FailureKind, message_for
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.watch_store import SQLiteWatchStore
from yoyackbot.workflow import build_workflow

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


def test_configuration_defaults_and_independent_unit_limits() -> None:
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "test-only"})
    assert (settings.max_minutes, settings.max_hours, settings.max_days, settings.max_weeks) == (
        1440,
        168,
        30,
        4,
    )
    assert settings.cache_retention_days == 30
    assert settings.timezone.key == "Asia/Seoul"
    assert "test-only" not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("YOYACK_MAX_MESSAGES", "not-a-number"),
        ("YOYACK_MAX_DAYS", "0"),
        ("YOYACK_CACHE_RETENTION_DAYS", "31"),
        ("YOYACK_MAX_DAYS", "31"),
        ("YOYACK_MAX_WEEKS", "5"),
        ("YOYACK_MAX_HOURS", "721"),
        ("YOYACK_MAX_MINUTES", "43201"),
        ("YOYACK_DISCORD_MESSAGE_LIMIT", "2001"),
        ("YOYACK_TIMEZONE", "invalid-zone"),
        ("YOYACK_CODEX_REASONING_EFFORT", "unsupported"),
    ],
)
def test_bad_settings_fail_before_start_without_echoing_values(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError) as exc:
        Settings.from_environment({"DISCORD_BOT_TOKEN": "test-only", name: value})
    assert name in str(exc.value)
    assert "test-only" not in str(exc.value)


def test_runtime_collectors_receive_the_same_thirty_day_policy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "yoyackbot.workflow.CodexSummaryEngine.from_settings", lambda _settings: object()
    )
    path = tmp_path / "messages.db"
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "test-only", "YOYACK_DB_PATH": str(path),
    })
    workflow = build_workflow(
        settings, None, SQLiteWatchStore(path), SQLiteMessageStore(path)
    )
    collector = workflow.collector
    assert collector.max_days == 30
    assert (collector.time.retention_days, collector.time.max_days) == (30, 30)
    assert (collector.count.retention_days, collector.count.max_days) == (30, 30)

    shorter = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "test-only", "YOYACK_DB_PATH": str(path),
        "YOYACK_MAX_DAYS": "7",
    })
    limited = build_workflow(
        shorter, None, SQLiteWatchStore(path), SQLiteMessageStore(path)
    )
    assert limited.collector.max_days == 7
    assert (limited.collector.time.retention_days, limited.collector.time.max_days) == (30, 7)


def test_time_and_count_contracts_cannot_be_confused() -> None:
    time_range = RangeRequest(RequestKind.TIME, NOW, start=NOW - timedelta(hours=1))
    count_range = RangeRequest(RequestKind.COUNT, NOW, count=100)
    assert time_range.start is not None and time_range.count is None
    assert count_range.start is None and count_range.count == 100
    with pytest.raises(ValueError):
        RangeRequest(RequestKind.COUNT, NOW, start=NOW - timedelta(hours=1), count=100)


def test_cross_layer_request_and_result_fixture() -> None:
    message = MessageRecord(1, 10, 20, 30, "철수", "합성 대화", NOW)
    coverage = CoverageInterval(20, NOW - timedelta(hours=1), NOW)
    request = SummaryRequest(10, 20, 30, RangeRequest(RequestKind.COUNT, NOW, count=1))
    result = SummaryResult("철수는 합성 대화를 하였소.", "test-model", 1)
    assert message.channel_id == coverage.channel_id == request.channel_id
    assert result.request_message_count == request.requested_range.count


def test_user_errors_do_not_expose_internal_details() -> None:
    for kind in FailureKind:
        message = message_for(kind)
        assert message
        assert "/var/" not in message
        assert "Traceback" not in message
        assert "TOKEN" not in message
