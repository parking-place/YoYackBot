"""Pinned Codex CLI/model contract; request execution is added in later phases."""

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from yoyackbot.config import Settings

PINNED_CLI_VERSION = "codex-cli 0.158.0"
REQUIRED_MODEL = "gpt-6-luna"
REQUIRED_EFFORT = "low"


class CodexFailure(Enum):
    AUTH = "auth"
    MODEL = "model"
    LIMIT = "limit"
    PROCESS = "process"


class CodexContractError(RuntimeError):
    """The configured model or CLI cannot satisfy the required contract."""


@dataclass(frozen=True)
class CodexContract:
    executable: str
    model: str
    reasoning_effort: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "CodexContract":
        if settings.codex_model != REQUIRED_MODEL or settings.codex_reasoning_effort != REQUIRED_EFFORT:
            raise CodexContractError("The required GPT-6 Luna Low configuration is unavailable")
        return cls(settings.codex_executable, settings.codex_model, settings.codex_reasoning_effort)

    def version_matches(self) -> bool:
        try:
            result = subprocess.run(
                [self.executable, "--version"], capture_output=True, text=True, timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0 and result.stdout.strip() == PINNED_CLI_VERSION

    def authentication_ready(self) -> bool:
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
                "--config", 'permissions.summary-read.filesystem={":root"="deny",'
                '":minimal"="read","/work"="read","/auth"="deny","/output"="deny"}',
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
        "rate limit", "usage limit", "quota", "http 429",
    )):
        return CodexFailure.LIMIT
    return CodexFailure.PROCESS
