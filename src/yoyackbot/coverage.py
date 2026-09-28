"""Half-open verified intervals and gaps independent of message counts."""

from collections.abc import Iterable

from yoyackbot.domain import CoverageInterval


def merge_intervals(
    channel_id: int, intervals: Iterable[CoverageInterval]
) -> list[CoverageInterval]:
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    if any(item.channel_id != channel_id for item in ordered):
        raise ValueError("coverage intervals must belong to one channel")
    merged: list[CoverageInterval] = []
    for interval in ordered:
        if merged and interval.start <= merged[-1].end:
            previous = merged[-1]
            merged[-1] = CoverageInterval(channel_id, previous.start, max(previous.end, interval.end))
        else:
            merged.append(interval)
    return merged


def missing_intervals(
    request: CoverageInterval,
    covered: Iterable[CoverageInterval],
    *,
    recheck: Iterable[CoverageInterval] = (),
) -> list[CoverageInterval]:
    """Return gaps plus stale ranges needing a fresh History pass."""
    gaps: list[CoverageInterval] = []
    cursor = request.start
    for interval in merge_intervals(request.channel_id, covered):
        if interval.end <= cursor or interval.start >= request.end:
            continue
        if interval.start > cursor:
            gaps.append(CoverageInterval(request.channel_id, cursor, min(interval.start, request.end)))
        cursor = min(request.end, max(cursor, interval.end))
        if cursor >= request.end:
            break
    if cursor < request.end:
        gaps.append(CoverageInterval(request.channel_id, cursor, request.end))
    for interval in merge_intervals(request.channel_id, recheck):
        start = max(request.start, interval.start)
        end = min(request.end, interval.end)
        if start < end:
            gaps.append(CoverageInterval(request.channel_id, start, end))
    return merge_intervals(request.channel_id, gaps)
