"""Validated runtime configuration with secret-safe errors."""

import stat
from collections.abc import Mapping
from dataclasses import dataclass
from os import environ
from pathlib import Path
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
    codex_auth_directory: Path
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
    queue_wait_seconds: int
    max_input_bytes: int
    max_output_bytes: int
    max_history_pages: int
    dev_guild_id: int | None = None

    @classmethod
    def from_environment(cls, source: Mapping[str, str] | None = None) -> "Settings":
        values = environ if source is None else source
        credentials_root = values.get("CREDENTIALS_DIRECTORY", "").strip()
        token_file = (
            str(Path(credentials_root) / "discord_token") if credentials_root
            else values.get("DISCORD_BOT_TOKEN_FILE", "").strip()
        )
        if token_file:
            path = Path(token_file)
            if not path.is_absolute():
                raise ConfigurationError("DISCORD_BOT_TOKEN_FILE must be absolute")
            try:
                info = path.stat()
                if not stat.S_ISREG(info.st_mode) or (
                    not credentials_root and info.st_mode & 0o077
                ):
                    raise ConfigurationError("DISCORD_BOT_TOKEN_FILE is not private")
                token = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as exc:
                raise ConfigurationError("DISCORD_BOT_TOKEN_FILE is unavailable") from exc
        else:
            token = values.get("DISCORD_BOT_TOKEN", "")
        if not token:
            raise ConfigurationError("Discord bot credential is not set")

        zone_name = _text(values, "YOYACK_TIMEZONE", "Asia/Seoul")
        try:
            timezone = ZoneInfo(zone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError("YOYACK_TIMEZONE is not recognized") from exc

        effort = _text(values, "YOYACK_CODEX_REASONING_EFFORT", "low")
        if effort not in {"minimal", "low", "medium", "high", "xhigh"}:
            raise ConfigurationError("YOYACK_CODEX_REASONING_EFFORT is unsupported")

        retention = _integer(values, "YOYACK_CACHE_RETENTION_DAYS", 30)
        if retention > 30:
            raise ConfigurationError("YOYACK_CACHE_RETENTION_DAYS cannot exceed 30")
        max_days = _integer(values, "YOYACK_MAX_DAYS", 30)
        if max_days > 30:
            raise ConfigurationError("YOYACK_MAX_DAYS cannot exceed 30")
        max_weeks = _integer(values, "YOYACK_MAX_WEEKS", 4)
        if max_weeks > 4:
            raise ConfigurationError("YOYACK_MAX_WEEKS cannot exceed 4")
        max_hours = _integer(values, "YOYACK_MAX_HOURS", 168)
        if max_hours > 720:
            raise ConfigurationError("YOYACK_MAX_HOURS cannot exceed 720")
        max_minutes = _integer(values, "YOYACK_MAX_MINUTES", 1440)
        model_concurrency = _integer(values, "YOYACK_CODEX_CONCURRENCY", 4)
        if model_concurrency > 4:
            raise ConfigurationError("YOYACK_CODEX_CONCURRENCY cannot exceed 4")
        if max_minutes > 43_200:
            raise ConfigurationError("YOYACK_MAX_MINUTES cannot exceed 43200")
        message_limit = _integer(values, "YOYACK_DISCORD_MESSAGE_LIMIT", 1900)
        if message_limit > 2000:
            raise ConfigurationError("YOYACK_DISCORD_MESSAGE_LIMIT cannot exceed 2000")

        dev_guild_raw = values.get("YOYACK_DEV_GUILD_ID", "").strip()
        if dev_guild_raw:
            try:
                dev_guild_id = int(dev_guild_raw)
            except ValueError as exc:
                raise ConfigurationError("YOYACK_DEV_GUILD_ID must be an integer") from exc
            if dev_guild_id < 1:
                raise ConfigurationError("YOYACK_DEV_GUILD_ID must be positive")
        else:
            dev_guild_id = None

        return cls(
            discord_bot_token=token,
            database_path=Path(_text(values, "YOYACK_DB_PATH", "runtime/messages.db")),
            codex_executable=_text(values, "YOYACK_CODEX_EXECUTABLE", "codex"),
            codex_auth_directory=Path(_text(
                values, "YOYACK_CODEX_AUTH_DIRECTORY", str(Path.home() / "model-auth")
            )),
            codex_model=_text(values, "YOYACK_CODEX_MODEL", "gpt-6-luna"),
            codex_reasoning_effort=effort,
            timezone=timezone,
            default_minutes=_integer(values, "YOYACK_DEFAULT_MINUTES", 60),
            success_cooldown_seconds=_integer(
                values, "YOYACK_SUCCESS_COOLDOWN_SECONDS", 60, minimum=0
            ),
            max_minutes=max_minutes,
            max_hours=max_hours,
            max_days=max_days,
            max_weeks=max_weeks,
            max_messages=_integer(values, "YOYACK_MAX_MESSAGES", 1000),
            codex_timeout_seconds=_integer(values, "YOYACK_CODEX_TIMEOUT_SECONDS", 120),
            input_directory=Path(_text(values, "YOYACK_INPUT_DIRECTORY", "runtime/input")),
            cache_retention_days=retention,
            cache_cleanup_interval_seconds=_integer(
                values, "YOYACK_CACHE_CLEANUP_INTERVAL_SECONDS", 3600
            ),
            discord_message_limit=message_limit,
            codex_concurrency=model_concurrency,
            queue_capacity=_integer(values, "YOYACK_QUEUE_CAPACITY", 8, minimum=0),
            queue_wait_seconds=_integer(values, "YOYACK_QUEUE_WAIT_SECONDS", 600),
            max_input_bytes=_integer(values, "YOYACK_MAX_INPUT_BYTES", 1_000_000),
            max_output_bytes=_integer(values, "YOYACK_MAX_OUTPUT_BYTES", 50_000),
            max_history_pages=_integer(values, "YOYACK_MAX_HISTORY_PAGES", 100),
            dev_guild_id=dev_guild_id,
        )
