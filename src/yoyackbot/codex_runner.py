"""Run one Codex summary with only its input and final-output directory mounted."""

import asyncio
import os
import pwd
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from yoyackbot.codex import CodexContract, CodexFailure, classify_cli_failure
from yoyackbot.input_files import InputWorkspace

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class CodexRunError(RuntimeError):
    """Safe category; CLI stdout/stderr and conversation text are never retained."""

    def __init__(self, kind: CodexFailure) -> None:
        super().__init__(kind.value)
        self.kind = kind


def final_text(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CodexRunError(CodexFailure.PROCESS) from exc
    clean = _ANSI.sub("", text)
    clean = "".join(char for char in clean if char in "\n\t" or ord(char) >= 32).strip()
    if not clean:
        raise CodexRunError(CodexFailure.PROCESS)
    return clean


@dataclass(frozen=True)
class SandboxedCodex:
    contract: CodexContract
    auth_file: Path
    bwrap_executable: Path = Path("/usr/bin/bwrap")

    def command(self, workspace: InputWorkspace) -> list[str]:
        if not Path(self.contract.executable).is_absolute() or not self.bwrap_executable.is_absolute():
            raise CodexRunError(CodexFailure.PROCESS)
        if workspace.log_file.parent != workspace.directory or not workspace.directory.is_absolute():
            raise CodexRunError(CodexFailure.PROCESS)
        try:
            auth = self.auth_file.lstat()
            source = workspace.log_file.lstat()
            directory = workspace.directory.lstat()
        except OSError as exc:
            raise CodexRunError(CodexFailure.PROCESS) from exc
        if (
            not stat.S_ISREG(auth.st_mode)
            or auth.st_uid != os.geteuid()
            or auth.st_mode & 0o077
            or not stat.S_ISREG(source.st_mode)
            or source.st_uid != os.geteuid()
            or source.st_mode & 0o077
            or not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077
        ):
            raise CodexRunError(CodexFailure.PROCESS)
        cli = replace(self.contract, executable="/bin/codex").arguments(
            working_directory=Path("/work"), output_file=Path("/output/final.txt"),
            restricted=True,
        )
        return [
            str(self.bwrap_executable), "--die-with-parent", "--unshare-all", "--share-net",
            "--new-session", "--tmpfs", "/", "--dir", "/bin", "--dir", "/lib",
            "--dir", "/lib64", "--dir", "/etc",
            "--dir", "/etc/ssl", "--dir", "/auth", "--dir", "/work",
            "--dir", "/output", "--dir", "/empty", "--dir", "/tmp",
            "--dev", "/dev", "--proc", "/proc",
            "--ro-bind", self.contract.executable, "/bin/codex",
            "--ro-bind", str(self.bwrap_executable), "/bin/bwrap",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/ssl/certs", "/etc/ssl/certs",
            "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
            "--ro-bind", "/etc/hosts", "/etc/hosts",
            "--ro-bind", str(self.auth_file), "/auth/auth.json",
            "--ro-bind", str(workspace.log_file), "/work/conversation.jsonl",
            "--bind", str(workspace.directory), "/output",
            "--clearenv", "--setenv", "HOME", "/empty",
            "--setenv", "CODEX_HOME", "/auth", "--setenv", "PATH", "/bin",
            "--setenv", "TMPDIR", "/tmp", "--setenv", "LANG", "C.UTF-8",
            "--chdir", "/work", *cli,
        ]

    async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
        """Return only the last model message; lifecycle limits are added in P4."""
        if not prompt:
            raise ValueError("Summary prompt must be nonempty")
        command = self.command(workspace)
        account = pwd.getpwuid(os.geteuid())
        env = {"PATH": "/usr/bin:/bin", "HOME": account.pw_dir, "LANG": "C.UTF-8"}
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=env, start_new_session=True,
            )
            _stdout, stderr = await process.communicate(prompt.encode("utf-8"))
        except OSError as exc:
            raise CodexRunError(CodexFailure.PROCESS) from exc
        if process.returncode != 0:
            kind = classify_cli_failure(process.returncode, stderr.decode("utf-8", "replace"))
            raise CodexRunError(kind or CodexFailure.PROCESS)
        try:
            return final_text((workspace.directory / "final.txt").read_bytes())
        except OSError as exc:
            raise CodexRunError(CodexFailure.PROCESS) from exc
