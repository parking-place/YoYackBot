"""1.4.0 처형 log: timeouts applied, extended or lifted, read from the server's audit log."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import discord

NO_REASON = "사유 없음"
_REASON_SHOWN = 400


@dataclass(frozen=True)
class TimeoutEvent:
    kind: str                 # "apply", "extend" or "release"
    executor_id: int | None
    target_id: int
    until: datetime | None    # end of the timeout (apply/extend)
    reason: str | None
    at: datetime


def timeout_event(entry: object) -> TimeoutEvent | None:
    """A member update that set, moved or cleared `timed_out_until`; anything else is None."""
    if getattr(entry, "action", None) is not discord.AuditLogAction.member_update:
        return None
    after = getattr(entry, "after", None)
    if after is None or not hasattr(after, "timed_out_until"):
        return None
    before_until = getattr(getattr(entry, "before", None), "timed_out_until", None)
    after_until = after.timed_out_until
    target_id = getattr(entry, "_target_id", None) or getattr(getattr(entry, "target", None), "id", None)
    at = getattr(entry, "created_at", None)
    if target_id is None or at is None:
        return None
    if after_until is None:
        if before_until is None:
            return None
        kind = "release"
    else:
        kind = "extend" if before_until is not None and before_until > at else "apply"
    return TimeoutEvent(kind, getattr(entry, "user_id", None), int(target_id), after_until,
                        getattr(entry, "reason", None), at)


def duration_text(span: timedelta) -> str:
    seconds = max(1, math.ceil(span.total_seconds()))
    parts = []
    for unit, size in (("일", 86400), ("시간", 3600), ("분", 60), ("초", 1)):
        count, seconds = divmod(seconds, size)
        if count:
            parts.append(f"{count}{unit}")
    return " ".join(parts[:2])


def reason_text(reason: str | None) -> str:
    cleaned = " ".join((reason or "").split())
    if not cleaned:
        return NO_REASON
    return cleaned if len(cleaned) <= _REASON_SHOWN else cleaned[:_REASON_SHOWN] + "…"


def log_message(event: TimeoutEvent, executor_id: int | None) -> str:
    """The posted line. Mentions are shown but never ping (sent with no allowed mentions)."""
    executor = f"<@{executor_id}>" if executor_id else "알 수 없는 사람"
    target = f"<@{event.target_id}>"
    reason = reason_text(event.reason)
    if event.kind == "release":
        return f"🕊️ **사면** — {executor}이(가) {target}의 처형을 풀었소.\n📝 사유: {reason}"
    assert event.until is not None
    stamp = int(event.until.timestamp())
    head = "⚔️ **처형 연장**" if event.kind == "extend" else "⚔️ **처형**"
    return (
        f"{head} — 처형자 {executor} → 처형인 {target}\n"
        f"⏱️ {duration_text(event.until - event.at)} (<t:{stamp}:f>까지)\n📝 사유: {reason}"
    )
