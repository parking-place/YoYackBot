"""Read-only, current-Guild status for `!!요약좀 상태`; never invents a healthy value."""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from yoyackbot.codex import CodexContract, CodexContractError
from yoyackbot.config import Settings

UNKNOWN = "확인할 수 없소."


@dataclass(frozen=True)
class StatusReport:
    gateway_ready: bool
    watched_channels: int | None
    cached_messages: int | None
    database_bytes: int | None
    model: str | None
    last_success: datetime | None
    last_success_known: bool

    @property
    def healthy(self) -> bool:
        return (
            self.gateway_ready and self.watched_channels is not None
            and self.cached_messages is not None and self.database_bytes is not None
            and self.model is not None and self.last_success_known
        )


def database_bytes(path: Path) -> int | None:
    """Main file plus an existing WAL; the transient SHM and rollback journal are excluded."""
    try:
        total = path.stat().st_size
    except OSError:
        return None
    wal = path.with_name(path.name + "-wal")
    try:
        total += wal.stat().st_size
    except FileNotFoundError:
        pass
    except OSError:
        return None
    return total


def read_guild_counts(
    path: Path, guild_id: int,
) -> tuple[int, int, datetime | None]:
    """Count only this Guild's watched channels, cached messages, and last full success."""
    if guild_id < 1:
        raise ValueError("guild_id must be positive")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    try:
        watched = connection.execute(
            "SELECT COUNT(*) FROM watched_channels WHERE guild_id=?", (guild_id,)
        ).fetchone()[0]
        cached = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE guild_id=?", (guild_id,)
        ).fetchone()[0]
        last = connection.execute(
            "SELECT MAX(c.last_success_us) FROM summary_cooldowns c "
            "JOIN watched_channels w ON w.guild_id=c.guild_id AND w.channel_id=c.channel_id "
            "WHERE c.guild_id=?", (guild_id,)
        ).fetchone()[0]
    finally:
        connection.close()
    when = None if last is None else datetime.fromtimestamp(last / 1_000_000, UTC)
    return watched, cached, when


def model_label(settings: Settings) -> str | None:
    """Show the configured model only when the pinned CLI and its private auth are ready."""
    try:
        contract = CodexContract.from_settings(settings)
    except CodexContractError:
        return None
    if not contract.version_matches() or not contract.authentication_ready(
        settings.codex_auth_directory
    ):
        return None
    return f"{contract.model} / {contract.reasoning_effort}"


def collect_status(
    settings: Settings, guild_id: int, *, gateway_ready: bool,
    model_reader: Callable[[Settings], str | None] = model_label,
) -> StatusReport:
    try:
        watched, cached, last = read_guild_counts(settings.database_path, guild_id)
        known = True
    except sqlite3.Error:
        watched = cached = last = None
        known = False
    try:
        model = model_reader(settings)
    except OSError:
        model = None
    return StatusReport(
        gateway_ready, watched, cached, database_bytes(settings.database_path), model,
        last, known,
    )


def _ago(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 60:
        return "방금 전이오."
    if seconds < 3600:
        return f"{seconds // 60}분 전이오."
    if seconds < 86_400:
        return f"{seconds // 3600}시간 전이오."
    return f"{seconds // 86_400}일 전이오."


def status_message(report: StatusReport, now: datetime) -> str:
    def value(item: object, text: str) -> str:
        return UNKNOWN if item is None else text

    if not report.last_success_known:
        last = UNKNOWN
    elif report.last_success is None:
        last = "기록이 없소."
    else:
        last = _ago(report.last_success, now)
    size = report.database_bytes
    return "\n".join([
        "📜🔍 현재 형편을 살펴보았소. 🧐",
        "",
        "🩺 상태: " + ("평온하오. 😌" if report.healthy else "점검이 필요하오. 🚨"),
        "📡 주시 채널: " + value(report.watched_channels, f"{report.watched_channels}곳이오."),
        "💬 캐시된 대화: " + value(report.cached_messages, f"{report.cached_messages or 0:,}건이오."),
        "💾 DB 크기: " + value(size, f"{(size or 0) / 1_000_000:.1f} MB이오."),
        "🤖 Codex: " + (report.model or UNKNOWN),
        "🕒 마지막 요약: " + last,
    ])
