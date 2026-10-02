"""Pinned Codex CLI/model contract; request execution is added in later phases."""

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

from yoyackbot.config import Settings

PINNED_CLI_VERSION = "codex-cli 0.158.0"
REQUIRED_MODEL = "gpt-6-luna"
# low is the default; operators may raise it to medium in the service environment.
ALLOWED_EFFORTS = frozenset({"low", "medium"})


class CodexFailure(Enum):
    AUTH = "auth"
    MODEL = "model"
    LIMIT = "limit"
    USAGE_LIMIT = "usage_limit"
    PROCESS = "process"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    OUTPUT_INVALID = "output_invalid"
    INPUT_LIMIT = "input_limit"


class CodexContractError(RuntimeError):
    """The configured model or CLI cannot satisfy the required contract."""

    def __init__(self, message: str, *, reason: str = "config") -> None:
        super().__init__(message)
        self.reason = reason


def resolve_executable(value: str) -> str:
    """A bare name is looked up on PATH; the summary runner and usage reader need a full path."""
    if os.path.isabs(value):
        return value
    if os.sep in value:
        raise CodexContractError("Codex CLI path must be absolute or a PATH name")
    found = shutil.which(value)
    if found is None or not os.path.isabs(found):
        raise CodexContractError("Codex CLI is not on PATH", reason="executable_missing")
    return found


def pin_executable(settings: Settings) -> Settings:
    """Resolve once at start so readiness, summaries and usage all run the same file."""
    try:
        return replace(settings, codex_executable=resolve_executable(settings.codex_executable))
    except CodexContractError:
        return settings  # readiness and the engine report the same failure


@dataclass(frozen=True)
class CodexContract:
    executable: str
    model: str
    reasoning_effort: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "CodexContract":
        if (
            settings.codex_model != REQUIRED_MODEL
            or settings.codex_reasoning_effort not in ALLOWED_EFFORTS
        ):
            raise CodexContractError("The required GPT-6 Luna low/medium configuration is unavailable")
        return cls(
            resolve_executable(settings.codex_executable), settings.codex_model,
            settings.codex_reasoning_effort,
        )

    def executable_problem(self) -> str | None:
        """Classify a missing or non-runnable CLI before asking it for its version."""
        try:
            info = os.stat(self.executable)
        except OSError:
            return "executable_missing"
        if not stat.S_ISREG(info.st_mode) or not os.access(self.executable, os.X_OK):
            return "executable_not_runnable"
        return None

    def version_matches(self) -> bool:
        try:
            result = subprocess.run(
                [self.executable, "--version"], capture_output=True, text=True, timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == PINNED_CLI_VERSION

    def authentication_ready(self, auth_directory: Path | None = None) -> bool:
        if auth_directory is not None:
            try:
                directory = auth_directory.lstat()
                auth = (auth_directory / "auth.json").lstat()
                if (
                    not stat.S_ISDIR(directory.st_mode)
                    or directory.st_uid != os.geteuid()
                    or directory.st_mode & 0o077
                    or not stat.S_ISREG(auth.st_mode)
                    or auth.st_uid != os.geteuid()
                    or auth.st_mode & 0o077
                ):
                    return False
                return isinstance(json.loads((auth_directory / "auth.json").read_text()), dict)
            except (OSError, ValueError):
                return False
        try:
            result = subprocess.run(
                [self.executable, "login", "status"], capture_output=True, text=True,
                timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def arguments(
        self, *, working_directory: Path, output_file: Path, restricted: bool = False
    ) -> list[str]:
        if not working_directory.is_absolute() or not output_file.is_absolute():
            raise ValueError("Codex paths must be absolute")
        args = [
            self.executable, "exec", "--model", self.model,
            "--config", f"model_reasoning_effort={self.reasoning_effort}",
        ]
        if restricted:
            args.extend([
                "--config", 'default_permissions="summary-read"',
                "--config", 'approval_policy="never"',
                "--config", (
                    'permissions.summary-read.filesystem={":root"="deny",'
                    '":minimal"="read","/work"="read","/auth"="deny","/output"="deny"}'
                ),
                "--config", "permissions.summary-read.network.enabled=false",
                "--config", 'web_search="disabled"',
            ])
            for feature in ("apps", "browser_use", "computer_use", "plugins", "multi_agent"):
                args.extend(("--disable", feature))
        else:
            args.extend(("--sandbox", "read-only"))
        args.extend([
            "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--color", "never", "--cd", str(working_directory),
            "--output-last-message", str(output_file), "-",
        ])
        return args


def classify_cli_failure(exit_code: int, stderr: str) -> CodexFailure | None:
    """Classify locally but never retain or log the CLI's raw diagnostics."""
    if exit_code == 0:
        return None
    diagnostic = stderr.lower()
    if any(marker in diagnostic for marker in (
        "unsupported model", "unknown model", "invalid model", "model_not_found",
        "model is not supported",
    )):
        return CodexFailure.MODEL
    if any(marker in diagnostic for marker in (
        "not logged in", "authentication", "unauthorized", "invalid api key", "token expired",
        "failed to refresh token", "http 401",
    )):
        return CodexFailure.AUTH
    if any(marker in diagnostic for marker in (
        "usage limit reached", "reached your usage limit", "hit your usage limit",
        "usage_limit_reached", "usage_limit_exceeded", "credits_depleted", "out of credits",
        "quota exceeded", "quota_exceeded", "insufficient_quota",
    )):
        return CodexFailure.USAGE_LIMIT
    if any(marker in diagnostic for marker in (
        "rate limit", "rate_limit", "too many requests", "http 429", "server overloaded",
        "server_overloaded", "usage limit", "quota",
    )):
        return CodexFailure.LIMIT
    return CodexFailure.PROCESS
