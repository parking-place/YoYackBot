"""Operational records must be useful without copying private input."""

import json
import logging
from datetime import UTC, datetime, timedelta

from yoyackbot.health import read_heartbeat, write_heartbeat
from yoyackbot.ops import RequestMetrics


def test_request_metrics_are_allowlisted_and_contain_no_user_text(caplog) -> None:
    private_text = "SECRET_CONVERSATION_AND_TOKEN"
    metrics = RequestMetrics(private_text)
    metrics.selected_count = 3
    metrics.cache_count = 1
    metrics.history_count = 2
    metrics.history_pages = 2
    metrics.model_result = "success"
    metrics.post_result = "success"
    metrics.outcome = "success"
    metrics.error_kind = private_text
    with caplog.at_level(logging.INFO, logger="yoyackbot.metrics"):
        metrics.emit()
    assert private_text not in caplog.text
    record = json.loads(caplog.records[-1].message)
    assert record["event"] == "summary_request"
    assert record["selected_count"] == 3
    assert record["cache_count"] == 1
    assert record["history_count"] == 2
    assert record["history_pages"] == 2
    assert record["kind"] == "unknown"
    assert record["error_kind"] == "unexpected"
    assert record["duration_ms"] >= 0
    assert set(record) == {
        "event", "request_id", "kind", "selected_count", "cache_count", "history_count",
        "history_pages", "cache_fallback",
        "duration_ms", "model_result", "post_result", "outcome", "error_kind",
    }


def test_gateway_health_separates_process_and_connection(tmp_path, monkeypatch) -> None:
    write_heartbeat(tmp_path, gateway_ready=False)
    assert read_heartbeat(tmp_path) == (True, False)
    write_heartbeat(tmp_path, gateway_ready=True)
    assert read_heartbeat(tmp_path) == (True, True)
    heartbeat = tmp_path / "gateway-health.json"
    payload = json.loads(heartbeat.read_text())
    payload["updated_at"] = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    heartbeat.write_text(json.dumps(payload))
    assert read_heartbeat(tmp_path) == (False, False)
    write_heartbeat(tmp_path, gateway_ready=True)
    monkeypatch.setattr("yoyackbot.health.os.kill", lambda *_args: (_ for _ in ()).throw(
        ProcessLookupError()
    ))
    assert read_heartbeat(tmp_path) == (False, False)
