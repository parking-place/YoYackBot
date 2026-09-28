"""KST range headers and safe, ordered Discord message chunks."""

import re
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryResult

_MENTION = re.compile(r"<@(?P<role>&)?!?(?P<user>\d+)>|<#(?P<channel>\d+)>")


def utf16_length(text: str) -> int:
    """Count conservatively for Discord's UTF-16 based message limit."""
    return sum(2 if ord(character) > 0xFFFF else 1 for character in text)


def sanitize_mentions(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group("channel") is not None:
            return "#채널"
        return "@역할" if match.group("role") else "@사용자"

    clean = _MENTION.sub(replace, text)
    return clean.replace("@everyone", "＠everyone").replace("@here", "＠here")


def _clock(value: datetime) -> str:
    hour = value.hour
    return f"{'오전' if hour < 12 else '오후'} {hour % 12 or 12}시 {value.minute:02d}분"


def range_header(
    request: RangeRequest, messages: Sequence[MessageRecord], timezone: ZoneInfo,
    *, posted_at: datetime | None = None,
) -> str:
    """Describe the actual selected interval ending at the request acceptance time."""
    if request.kind is RequestKind.COUNT:
        if not messages:
            raise ValueError("Count summary needs selected messages")
        beginning = min(item.created_at for item in messages)
    else:
        assert request.start is not None
        beginning = request.start
    local_start = beginning.astimezone(timezone)
    local_end = request.accepted_at.astimezone(timezone)
    if (
        request.kind is RequestKind.TIME
        and local_start.date() == local_end.date()
        and local_start.hour == local_start.minute == 0
    ):
        label = "오늘 00시 00분"
    elif local_start.date() != local_end.date():
        year = f"{local_start.year}년 " if local_start.year != local_end.year else ""
        label = f"{year}{local_start.month}월 {local_start.day}일 {_clock(local_start)}"
    else:
        label = _clock(local_start)
    header = f"{label}부터 지금까지의 요약이오."
    if posted_at is not None and (posted_at - request.accepted_at).total_seconds() >= 60:
        header += f" (기준: {_clock(local_end)} KST)"
    return header


def _prefix_that_fits(text: str, budget: int) -> int:
    width = 0
    for index, character in enumerate(text):
        width += 2 if ord(character) > 0xFFFF else 1
        if width > budget:
            return index
    return len(text)


def split_body(text: str, budget: int) -> tuple[str, ...]:
    """Keep every source character; prefer paragraph and line breaks before hard cuts."""
    if budget < 1:
        raise ValueError("Message budget must be positive")
    chunks: list[str] = []
    remaining = text
    while remaining:
        end = _prefix_that_fits(remaining, budget)
        if end == len(remaining):
            chunks.append(remaining)
            break
        if end < 1:
            raise ValueError("A character cannot fit in the message budget")
        lower = max(1, end // 2)
        for separator in ("\n\n", "\n", "다. ", ". ", " "):
            boundary = remaining.rfind(separator, lower, end + 1)
            if boundary >= lower:
                end = boundary + len(separator)
                break
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    return tuple(chunks)


def format_summary(
    request: RangeRequest, messages: Sequence[MessageRecord], result: SummaryResult,
    timezone: ZoneInfo, *, limit: int = 1900, posted_at: datetime | None = None,
) -> tuple[str, ...]:
    """Place the range header once and balance split fenced Markdown blocks."""
    body = sanitize_mentions(result.text.strip())
    if not body:
        raise ValueError("Summary body must not be empty")
    header = range_header(request, messages, timezone, posted_at=posted_at)
    budget = limit - utf16_length(header) - 2 - 20
    if budget < 1:
        raise ValueError("Message limit leaves no room for summary")
    parts = split_body(body, budget)
    rendered: list[str] = []
    fenced = False
    for index, part in enumerate(parts, start=1):
        label = f"({index}/{len(parts)})\n" if len(parts) > 1 else ""
        prefix = f"{header}\n\n" if index == 1 else ""
        reopen = "```\n" if fenced else ""
        fenced = fenced ^ (part.count("```") % 2 == 1)
        close = "\n```" if fenced and index < len(parts) else ""
        chunk = prefix + label + reopen + part + close
        if utf16_length(chunk) > limit:
            raise ValueError("Formatted summary exceeds Discord message limit")
        rendered.append(chunk)
    return tuple(rendered)
