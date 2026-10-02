"""Allowlisted request diagnostics without Discord or model text."""

import json
import logging
import secrets
import time
from dataclasses import dataclass, field

LOGGER = logging.getLogger("yoyackbot.metrics")


@dataclass
class RequestMetrics:
    """Only fixed categories and numeric measurements may reach the journal."""

    request_kind: str
    mode: str = "short"
    request_id: str = field(default_factory=lambda: secrets.token_hex(8))
    started: float = field(default_factory=time.monotonic, repr=False)
    selected_count: int = 0
    cache_count: int = 0
    history_count: int = 0
    history_pages: int = 0
    cache_fallback: bool = False
    input_bytes: int = 0
    collection_ms: int = 0
    queue_ms: int = 0
    model_ms: int = 0
    model_result: str = "not_started"
    post_result: str = "not_started"
    outcome: str = "unknown"
    error_kind: str = "none"
    failure_detail: str = "none"
    rating: str = "none"
    rating_candidates: int = 0
    rating_similar: int = 0
    ongoing_jab: str = "none"
    topic_critique: str = "na"
    name_underline: str = "na"

    def emit(self) -> None:
        allowed_outcomes = {
            "success", "empty", "busy", "cooldown", "invalidated", "history_error",
            "model_error", "input_error", "post_error", "queue_full", "queue_timeout", "queue_closed",
            "channel_unavailable", "unexpected", "cancelled", "not_ready", "notice_error",
        }
        if self.outcome not in allowed_outcomes:
            self.outcome = "unexpected"
        payload = {
            "event": "summary_request",
            "request_id": self.request_id,
            "kind": self.request_kind if self.request_kind in {"time", "count"} else "unknown",
            "mode": self.mode if self.mode in {"short", "long", "detailed"} else "unknown",
            "selected_count": max(0, self.selected_count),
            "cache_count": max(0, self.cache_count),
            "history_count": max(0, self.history_count),
            "history_pages": max(0, self.history_pages),
            "cache_fallback": self.cache_fallback,
            "input_bytes": max(0, self.input_bytes),
            "collection_ms": max(0, self.collection_ms),
            "queue_ms": max(0, self.queue_ms),
            "model_ms": max(0, self.model_ms),
            "duration_ms": max(0, round((time.monotonic() - self.started) * 1000)),
            "model_result": self.model_result if self.model_result in {
                "not_started", "success", "failure", "cancelled"
            } else "failure",
            "post_result": self.post_result if self.post_result in {
                "not_started", "success", "failure", "partial"
            } else "failure",
            "outcome": self.outcome,
            "error_kind": self.error_kind if self.error_kind in {
                "none", "history", "input", "model", "send", "queue", "permission", "unexpected"
            } else "unexpected",
            "rating": self.rating if self.rating in {
                "none", "picked", "regenerated", "fallback_summary", "fallback_first",
                "missing", "skipped",
            } else "none",
            "rating_candidates": min(10, max(0, self.rating_candidates)),
            "rating_similar": min(10, max(0, self.rating_similar)),
            "ongoing_jab": self.ongoing_jab if self.ongoing_jab in {
                "none", "retried", "retried_left"
            } else "none",
            "topic_critique": self.topic_critique if self.topic_critique in {
                "all", "partial", "none", "na"
            } else "na",
            "name_underline": self.name_underline if self.name_underline in {
                "all", "partial", "none", "na"
            } else "na",
            "failure_detail": self.failure_detail if self.failure_detail in {
                "none", "input_file", "input_size", "auth", "model", "limit", "usage_limit", "process",
                "timeout",
                "output_limit", "output_invalid", "input_limit", "queue_full",
                "queue_timeout", "queue_closed", "history", "permission", "send",
                "unexpected",
            } else "unexpected",
        }
        LOGGER.info("%s", json.dumps(payload, separators=(",", ":"), sort_keys=True))
