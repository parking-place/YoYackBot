"""Environment configuration with secret-safe validation."""

from dataclasses import dataclass
from os import environ


class ConfigurationError(ValueError):
    """A required setting is absent or invalid."""


@dataclass(frozen=True)
class Settings:
    discord_bot_token: str
    database_path: str
    codex_executable: str
    codex_model: str
    timezone: str

    @classmethod
    def from_environment(cls) -> "Settings":
        token = environ.get("DISCORD_BOT_TOKEN", "")
        if not token:
            raise ConfigurationError("DISCORD_BOT_TOKEN is not set")
        return cls(
            discord_bot_token=token,
            database_path=environ.get("YOYACK_DB_PATH", "runtime/messages.db"),
            codex_executable=environ.get("YOYACK_CODEX_EXECUTABLE", "codex"),
            codex_model=environ.get("YOYACK_CODEX_MODEL", "gpt-6-luna"),
            timezone=environ.get("YOYACK_TIMEZONE", "Asia/Seoul"),
        )
