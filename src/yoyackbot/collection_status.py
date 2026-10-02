"""F02: the current channel's collection stage for `!!요약좀 상태` and the not-ready notice.

Only this channel is described. Totals are unknown, so there is no percentage or ETA; a value
that could not be read is shown as unknown, never as zero.
"""

from datetime import datetime
from enum import Enum

from yoyackbot.backfill import CollectionProgress, _at, summary_ready
from yoyackbot.health import COLLECTION_OK

UNKNOWN = "확인할 수 없소."


class CollectionStage(Enum):
    INITIAL = "initial"
    RECHECK = "recheck"
    RETRY = "retry"
    BLOCKED = "blocked"
    NOTICE = "notice"
    GAP = "gap"
    READY = "ready"
    UNKNOWN = "unknown"


STAGE_TEXT = {
    CollectionStage.INITIAL: "📥 처음 수집하는 중이오.",
    CollectionStage.RECHECK: "🔄 연결이 끊긴 사이의 대화와 수정·삭제를 대조하는 중이오.",
    CollectionStage.RETRY: "⏳ 잠시 막혀 다시 시도하려고 기다리는 중이오.",
    CollectionStage.BLOCKED: "🚫 수집이 막혔소.",
    CollectionStage.NOTICE: "📣 수집은 끝났고 준비 안내를 올리려는 중이오.",
    CollectionStage.GAP: "🔌 연결이 끊겼던 구간을 점검하려고 기다리는 중이오.",
    CollectionStage.READY: "✅ 요약할 수 있소.",
    CollectionStage.UNKNOWN: "❔ 수집 형편을 " + UNKNOWN,
}
BLOCK_REASON = {
    "permission": "🔒 이유: 이 채널을 읽거나 쓸 권한이 없소.",
    "channel_gone": "🗑️ 이유: 채널을 찾을 수 없소.",
    "invalid_page": "🧩 이유: Discord 응답이 이상해 멈췄소.",
}
WORKER_STOPPED = "⚠️ 수집 일꾼이 지금 멈춰 있소. 관리자에게 알리시오."


def collection_stage(
    progress: CollectionProgress | None, *, now: datetime, cache_available: bool,
) -> CollectionStage:
    """The same conditions that decide whether a summary may run, in the user's words."""
    state = progress.state if progress is not None else None
    if progress is None or state is None:
        return CollectionStage.UNKNOWN
    if state.blocked_reason is not None:
        return CollectionStage.BLOCKED
    if not state.ready:
        if state.retry_at_us > _us(now):
            return CollectionStage.RETRY
        return CollectionStage.RECHECK if progress.recheck_pending else CollectionStage.INITIAL
    if progress.recheck_pending:
        return CollectionStage.RECHECK
    if not summary_ready(state):
        return CollectionStage.NOTICE
    if not cache_available:
        return CollectionStage.GAP
    return CollectionStage.READY


def _us(value: datetime) -> int:
    return round(value.timestamp() * 1_000_000)


def _ago(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 60:
        return "방금 전이오."
    if seconds < 3600:
        return f"{seconds // 60}분 전이오."
    if seconds < 86_400:
        return f"{seconds // 3600}시간 전이오."
    return f"{seconds // 86_400}일 전이오."


def _after(then: datetime, now: datetime) -> str:
    seconds = max(0, int((then - now).total_seconds()))
    if seconds < 60:
        return "곧이오."
    if seconds < 3600:
        return f"{seconds // 60}분 뒤이오."
    return f"{seconds // 3600}시간 뒤이오."


def collection_lines(
    progress: CollectionProgress | None, *, now: datetime, cache_available: bool,
    worker: str | None,
) -> list[str]:
    """The current channel's section of the status reply."""
    stage = collection_stage(progress, now=now, cache_available=cache_available)
    lines = ["📍 이 채널 수집: " + STAGE_TEXT[stage]]
    if stage is CollectionStage.BLOCKED:
        assert progress is not None and progress.state is not None
        lines.append(BLOCK_REASON.get(progress.state.blocked_reason or "", "❔ 이유: " + UNKNOWN))
    if progress is None:
        lines.append("💬 저장된 대화: " + UNKNOWN)
    else:
        if stage is not CollectionStage.READY:
            lines.append("📄 이번 수집에서 처리한 쪽: " + (
                UNKNOWN if progress.pages is None else f"{progress.pages:,}쪽이오."
            ))
            lines.append("🕒 마지막 진척: " + (
                UNKNOWN if progress.pages is None
                else "아직 없소." if progress.last_progress is None
                else _ago(progress.last_progress, now)
            ))
        lines.append(f"💬 이 채널에 저장된 대화: {progress.stored_messages:,}건이오.")
        state = progress.state
        if (
            state is not None and stage not in (CollectionStage.BLOCKED, CollectionStage.READY)
            and state.retry_at_us > _us(now)
        ):
            lines.append("🔁 다음 재시도: " + _after(_at(state.retry_at_us), now))
    if stage not in (CollectionStage.READY, CollectionStage.BLOCKED) and worker not in COLLECTION_OK:
        lines.append(WORKER_STOPPED)
    return lines


def not_ready_detail(
    progress: CollectionProgress | None, *, now: datetime, cache_available: bool,
    worker: str | None,
) -> str:
    """One or two short lines appended to the not-ready notice."""
    stage = collection_stage(progress, now=now, cache_available=cache_available)
    lines = [STAGE_TEXT[stage]]
    if stage is CollectionStage.BLOCKED and progress is not None and progress.state is not None:
        lines.append(BLOCK_REASON.get(progress.state.blocked_reason or "", "❔ 이유: " + UNKNOWN))
    elif progress is not None:
        pages = "확인 불가" if progress.pages is None else f"{progress.pages:,}쪽"
        lines.append(f"📄 처리 {pages} · 💬 저장 {progress.stored_messages:,}건")
    if stage not in (CollectionStage.READY, CollectionStage.BLOCKED) and worker not in COLLECTION_OK:
        lines.append(WORKER_STOPPED)
    return "\n".join(lines)
