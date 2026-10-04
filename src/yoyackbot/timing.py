"""1.3.2: per-request stage timings in ms — fixed stage and call names and numbers, never text.

A timeline starts when the bot receives a command (0 ms) and follows the request through the
workflow, the engine and every Codex call (request-scoped context, like the fast tier). The
workflow writes it as one `request_timing` line after the request's metrics line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime

LOGGER = logging.getLogger("yoyackbot.timing")
STAGES = ("received", "admitted", "start_notice", "collected", "queued", "posted")
CALLS = frozenset({
    "summary", "summary_retry", "candidates", "judge", "candidates_retry",
    "idiom_candidates", "idiom_candidates_retry", "idiom_select",
})
KINDS = frozenset({"summary", "idiom"})
RESULTS = frozenset({"ok", "error", "cancelled", "running"})
# First model output lines the CLI writes to stderr after its start banner.
MODEL_OUTPUT_LINES = frozenset({"codex", "thinking", "exec"})


@dataclass
class CodexCall:
    label: str
    start_ms: int
    timeline: Timeline = field(repr=False)
    first_output_ms: int | None = None
    end_ms: int | None = None
    result: str = "running"


@dataclass
class Timeline:
    started: float = field(default_factory=time.monotonic)
    discord_delay_ms: int | None = None
    steps: list[tuple[str, int]] = field(default_factory=list)
    calls: list[CodexCall] = field(default_factory=list)
    claimed: bool = False

    def now_ms(self) -> int:
        return max(0, round((time.monotonic() - self.started) * 1000))

    def mark(self, stage: str) -> None:
        if stage in STAGES:
            self.steps.append((stage, self.now_ms()))

    def payload(self, kind: str, request_id: str, outcome: str) -> dict:
        return {
            "event": "request_timing",
            "request_id": request_id,
            "kind": kind if kind in KINDS else "unknown",
            "outcome": outcome,
            "discord_delay_ms": self.discord_delay_ms,
            "steps": [[name, ms] for name, ms in self.steps],
            "codex": [
                {
                    "n": number, "call": call.label if call.label in CALLS else "unknown",
                    "start": call.start_ms, "first_output": call.first_output_ms,
                    "end": call.end_ms, "result": call.result if call.result in RESULTS else "error",
                }
                for number, call in enumerate(self.calls, start=1)
            ],
            "total_ms": self.now_ms(),
        }

    def emit(self, kind: str, request_id: str, outcome: str) -> None:
        LOGGER.info("%s", json.dumps(
            self.payload(kind, request_id, outcome), separators=(",", ":"), sort_keys=True,
        ))


_TIMELINE: ContextVar[Timeline | None] = ContextVar("yoyack_timeline", default=None)
_CALL: ContextVar[CodexCall | None] = ContextVar("yoyack_codex_call", default=None)


def begin(created_at: datetime | None = None) -> Timeline:
    """Start at command receipt; Discord's message time gives the delay before it (approximate)."""
    timeline = Timeline()
    if isinstance(created_at, datetime) and created_at.tzinfo is not None:
        timeline.discord_delay_ms = round((datetime.now(UTC) - created_at).total_seconds() * 1000)
    timeline.mark("received")
    _TIMELINE.set(timeline)
    return timeline


def claim() -> Timeline:
    """The workflow takes the command's timeline once; a direct call starts its own."""
    timeline = _TIMELINE.get()
    if timeline is None or timeline.claimed:
        timeline = begin()
    timeline.claimed = True
    return timeline


def mark(stage: str) -> None:
    timeline = _TIMELINE.get()
    if timeline is not None:
        timeline.mark(stage)


class codex_call:
    """One Codex CLI run inside the current request's timeline (no-op without one)."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.call: CodexCall | None = None

    async def __aenter__(self) -> None:
        timeline = _TIMELINE.get()
        if timeline is not None:
            self.call = CodexCall(self.label, timeline.now_ms(), timeline)
            timeline.calls.append(self.call)
        self._token = _CALL.set(self.call)

    async def __aexit__(self, kind: type[BaseException] | None, *_rest: object) -> None:
        _CALL.reset(self._token)
        if self.call is not None:
            self.call.end_ms = self.call.timeline.now_ms()
            self.call.result = (
                "ok" if kind is None
                else "cancelled" if issubclass(kind, asyncio.CancelledError) else "error"
            )


def first_output() -> None:
    call = _CALL.get()
    if call is not None and call.first_output_ms is None:
        call.first_output_ms = call.timeline.now_ms()


class OutputWatch:
    """Find the first model output line in CLI stderr chunks, across chunk boundaries."""

    def __init__(self) -> None:
        self.found = False
        self._partial = b""

    def feed(self, chunk: bytes) -> None:
        if self.found:
            return
        data = self._partial + chunk
        *lines, self._partial = data.split(b"\n")
        if len(self._partial) > 64:
            self._partial = b"#"  # a long line can never be a bare marker line
        for line in lines:
            if line.strip().decode("utf-8", "replace") in MODEL_OUTPUT_LINES:
                self.found = True
                first_output()
                return
