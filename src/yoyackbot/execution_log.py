"""1.4.0 처형 log: timeouts applied, extended or lifted, read from the server's audit log.

1.4.1b: the user's layout, framed by rules, with a blank line between lines and an invisible
last line so consecutive logs stay apart (Discord drops trailing blank lines)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord

NO_REASON = "사유 없음"
UNKNOWN_PERSON = "알 수 없는 사람"
RULE = "-" * 54
GAP = "\u200b"  # a zero-width line: Discord keeps it, so the next message starts one line lower
DEFAULT_ZONE = ZoneInfo("Asia/Seoul")
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


def log_message(
    event: TimeoutEvent, executor_id: int | None, timezone: ZoneInfo | None = None,
) -> str:
    """The posted message. Mentions are shown but never ping (sent with no allowed mentions)."""
    executor = f"<@{executor_id}>" if executor_id else UNKNOWN_PERSON
    target = f"<@{event.target_id}>"
    reason = reason_text(event.reason)
    if event.kind == "release":
        lines = [
            "🕊️ 사면되었소",
            f"☠️{target} 을(를) 🗡️{executor} 이(가) 사면하였소",
            f'📜사유는 "{reason}" 이였소.',
            "🗽자유를 만끽하시오!⛓️‍💥",
        ]
    else:
        assert event.until is not None
        extend = event.kind == "extend"
        until = event.until.astimezone(timezone or DEFAULT_ZONE).strftime("%Y-%m-%d %H:%M")
        lines = [
            "⚔️처형을 연장했소" if extend else "⚔️처형했소",
            f"☠️{target} 을(를) 🗡️{executor} 이(가) "
            + ("처형을 연장하였소." if extend else "처형하였소."),
            f'📜사유는 "{reason}" 이며, ⏳{duration_text(event.until - event.at)} 동안 시체요.',
            f"🕑{until} 이후에 오시오🚨",
        ]
    return "\n".join([RULE, "\n\n".join(lines), RULE, GAP])
