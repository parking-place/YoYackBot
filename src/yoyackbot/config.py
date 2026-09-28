"""Validated runtime configuration with secret-safe errors."""

from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigurationError(ValueError):
    """A required setting is absent or invalid."""


def _integer(source: Mapping[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    raw = source.get(name, str(default))
    try:
        value = int(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} must be at least {minimum}")
    return value


def _text(source: Mapping[str, str], name: str, default: str) -> str:
    value = source.get(name, default).strip()
    if not value:
        raise ConfigurationError(f"{name} must not be empty")
    return value


@dataclass(frozen=True, repr=False)
class Settings:
    discord_bot_token: str
    database_path: Path
    codex_executable: str
    codex_model: str
    codex_reasoning_effort: str
    timezone: ZoneInfo
    default_minutes: int
    success_cooldown_seconds: int
    max_minutes: int
    max_hours: int
    max_days: int
    max_weeks: int
    max_messages: int
    codex_timeout_seconds: int
    input_directory: Path
    cache_retention_days: int
    cache_cleanup_interval_seconds: int
    discord_message_limit: int
    codex_concurrency: int
    queue_capacity: int
    max_input_bytes: int
    max_output_bytes: int
    max_history_pages: int

    @classmethod
    def from_environment(cls, source: Mapping[str, str] | None = None) -> "Settings":
        values = environ if source is None else source
        token = values.get("DISCORD_BOT_TOKEN", "")
        if not token:
            raise ConfigurationError("DISCORD_BOT_TOKEN is not set")

        zone_name = _text(values, "YOYACK_TIMEZONE", "Asia/Seoul")
        try:
            timezone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError("YOYACK_TIMEZONE is not recognized") from exc

        effort = _text(values, "YOYACK_CODEX_REASONING_EFFORT", "low")
        if effort not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise ConfigurationError("YOYACK_CODEX_REASONING_EFFORT is unsupported")

        retention = _integer(values, "YOYACK_CACHE_RETENTION_DAYS", 7)
        if retention > 7:
            raise ConfigurationError("YOYACK_CACHE_RETENTION_DAYS cannot exceed 7")
        message_limit = _integer(values, "YOYACK_DISCORD_MESSAGE_LIMIT", 1900)
        if message_limit > 2000:
            raise ConfigurationError("YOYACK_DISCORD_MESSAGE_LIMIT cannot exceed 2000")

        return cls(
            discord_bot_token=token,
            database_path=Path(_text(values, "YOYACK_DB_PATH", "runtime/messages.db")),
            codex_executable=_text(values, "YOYACK_CODEX_EXECUTABLE", "codex"),
            codex_model=_text(values, "YOYACK_CODEX_MODEL", "gpt-6-luna"),
            codex_reasoning_effort=effort,
            timezone=timezone,
            default_minutes=_integer(values, "YOYACK_DEFAULT_MINUTES", 60),
            success_cooldown_seconds=_integer(
                values, "YOYACK_SUCCESS_COOLDOWN_SECONDS", 300, minimum=0
            ),
            max_minutes=_integer(values, "YOYACK_MAX_MINUTES", 1440),
            max_hours=_integer(values, "YOYACK_MAX_HOURS", 168),
            max_days=_integer(values, "YOYACK_MAX_DAYS", 7),
            max_weeks=_integer(values, "YOYACK_MAX_WEEKS", 4),
            max_messages=_integer(values, "YOYACK_MAX_MESSAGES", 1000),
            codex_timeout_seconds=_integer(values, "YOYACK_CODEX_TIMEOUT_SECONDS", 120),
            input_directory=Path(_text(values, "YOYACK_INPUT_DIRECTORY", "runtime/input")),
            cache_retention_days=retention,
            cache_cleanup_interval_seconds=_integer(
                values, "YOYACK_CACHE_CLEANUP_INTERVAL_SECONDS", 3600
            ),
            discord_message_limit=message_limit,
            codex_concurrency=_integer(values, "YOYACK_CODEX_CONCURRENCY", 1),
            queue_capacity=_integer(values, "YOYACK_QUEUE_CAPACITY", 4),
            max_input_bytes=_integer(values, "YOYACK_MAX_INPUT_BYTES", 1_000_000),
            max_output_bytes=_integer(values, "YOYACK_MAX_OUTPUT_BYTES", 50_000),
            max_history_pages=_integer(values, "YOYACK_MAX_HISTORY_PAGES", 100),
        )
