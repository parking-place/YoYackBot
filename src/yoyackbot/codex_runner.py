"""Run one Codex summary with only its input and final-output directory mounted."""

import asyncio
import json
import os
import pwd
import re
import shutil
import signal
import stat
import tempfile
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


class _OutputExceeded(RuntimeError):
    """Internal signal to stop a CLI that exceeds its output budget."""


async def _bounded_read(stream: asyncio.StreamReader, limit: int) -> bytes:
    data = bytearray()
    while chunk := await stream.read(8192):
        if len(data) + len(chunk) > limit:
            raise _OutputExceeded
        data.extend(chunk)
    return bytes(data)


async def _send_prompt(stream: asyncio.StreamWriter, prompt: bytes) -> None:
    try:
        stream.write(prompt)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        stream.close()


async def _kill_group(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def _invoke(
    command: list[str], prompt: bytes, env: dict[str, str], timeout: float, output_limit: int
) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env, start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    tasks = [
        asyncio.create_task(_send_prompt(process.stdin, prompt)),
        asyncio.create_task(_bounded_read(process.stdout, output_limit)),
        asyncio.create_task(_bounded_read(process.stderr, output_limit)),
        asyncio.create_task(process.wait()),
    ]
    try:
        _, stdout, stderr, exit_code = await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        return exit_code, stdout, stderr
    except TimeoutError as exc:
        await _kill_group(process)
        raise CodexRunError(CodexFailure.TIMEOUT) from exc
    except _OutputExceeded as exc:
        await _kill_group(process)
        raise CodexRunError(CodexFailure.OUTPUT_LIMIT) from exc
    except BaseException:
        await _kill_group(process)
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
    code_mode_host: Path = Path("/usr/local/bin/yoyack-codex-code-mode-host")
    timeout_seconds: float = 120
    max_prompt_bytes: int = 65536
    max_output_bytes: int = 50000

    def command(self, workspace: InputWorkspace) -> list[str]:
        if (
            not Path(self.contract.executable).is_absolute()
            or not self.bwrap_executable.is_absolute()
        ):
            raise CodexRunError(CodexFailure.PROCESS)
        if (
            workspace.log_file.parent != workspace.directory
            or not workspace.directory.is_absolute()
            or workspace.output_directory.parent != workspace.directory
        ):
            raise CodexRunError(CodexFailure.PROCESS)
        try:
            auth = self.auth_file.lstat()
            auth_directory = self.auth_file.parent.lstat()
            source = workspace.log_file.lstat()
            directory = workspace.directory.lstat()
            output_directory = workspace.output_directory.lstat()
        except OSError as exc:
            raise CodexRunError(CodexFailure.PROCESS) from exc
        if (
            not stat.S_ISREG(auth.st_mode)
            or auth.st_uid != os.geteuid()
            or auth.st_mode & 0o077
            or self.auth_file.name != "auth.json"
            or not stat.S_ISDIR(auth_directory.st_mode)
            or auth_directory.st_uid != os.geteuid()
            or auth_directory.st_mode & 0o077
            or not stat.S_ISREG(source.st_mode)
            or source.st_uid != os.geteuid()
            or source.st_mode & 0o077
            or not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077
            or not stat.S_ISDIR(output_directory.st_mode)
            or output_directory.st_uid != os.geteuid()
            or output_directory.st_mode & 0o077
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
            "--ro-bind", str(self.code_mode_host), "/bin/codex-code-mode-host",
            "--ro-bind", str(self.bwrap_executable), "/bin/bwrap",
            "--ro-bind", "/bin/bash", "/bin/bash",
            "--ro-bind", "/bin/sh", "/bin/sh",
            "--ro-bind", "/bin/cat", "/bin/cat",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--ro-bind", "/etc/ssl/certs", "/etc/ssl/certs",
            "--ro-bind", "/etc/resolv.conf", "/etc/resolv.conf",
            "--ro-bind", "/etc/hosts", "/etc/hosts",
            "--bind", str(self.auth_file.parent), "/auth",
            "--ro-bind", str(workspace.log_file), "/work/conversation.jsonl",
            "--bind", str(workspace.output_directory), "/output",
            "--clearenv", "--setenv", "HOME", "/empty",
            "--setenv", "CODEX_HOME", "/auth", "--setenv", "PATH", "/bin",
            "--setenv", "TMPDIR", "/tmp", "--setenv", "LANG", "C.UTF-8",
            "--chdir", "/work", *cli,
        ]

    async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
        """Return the final model message and delete this request's files on every exit."""
        temporary_auth: Path | None = None
        try:
            encoded = prompt.encode("utf-8")
            if not encoded or len(encoded) > self.max_prompt_bytes:
                raise CodexRunError(CodexFailure.INPUT_LIMIT)
            if self.timeout_seconds <= 0 or self.max_output_bytes < 1:
                raise ValueError("Codex limits must be positive")
            self.command(workspace)
            temporary_auth = workspace.directory / "auth"
            temporary_auth.mkdir(mode=0o700)
            copied_auth = temporary_auth / "auth.json"
            shutil.copyfile(self.auth_file, copied_auth)
            copied_auth.chmod(0o600)
            command = replace(self, auth_file=copied_auth).command(workspace)
            account = pwd.getpwuid(os.geteuid())
            env = {"PATH": "/usr/bin:/bin", "HOME": account.pw_dir, "LANG": "C.UTF-8"}
            try:
                exit_code, _stdout, stderr = await _invoke(
                    command, encoded, env, self.timeout_seconds, self.max_output_bytes
                )
            except OSError as exc:
                raise CodexRunError(CodexFailure.PROCESS) from exc
            if exit_code != 0:
                kind = classify_cli_failure(exit_code, stderr.decode("utf-8", "replace"))
                raise CodexRunError(kind or CodexFailure.PROCESS)
            output = workspace.output_directory / "final.txt"
            try:
                fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                        raise CodexRunError(CodexFailure.PROCESS)
                    if info.st_size > self.max_output_bytes:
                        raise CodexRunError(CodexFailure.OUTPUT_LIMIT)
                    raw = stream.read(self.max_output_bytes + 1)
                    if len(raw) > self.max_output_bytes:
                        raise CodexRunError(CodexFailure.OUTPUT_LIMIT)
                    return final_text(raw)
            except OSError as exc:
                raise CodexRunError(CodexFailure.PROCESS) from exc
        finally:
            if temporary_auth is not None:
                self._persist_refreshed_auth(temporary_auth / "auth.json")
            workspace.close()

    def _persist_refreshed_auth(self, candidate: Path) -> None:
        """Only a valid updated auth.json escapes the disposable request directory."""
        try:
            info = candidate.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                return
            updated = candidate.read_bytes()
            if updated == self.auth_file.read_bytes():
                return
            if not isinstance(json.loads(updated), dict):
                return
            fd, name = tempfile.mkstemp(prefix=".auth-update-", dir=self.auth_file.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(updated)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(name, 0o600)
                os.replace(name, self.auth_file)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        except (OSError, ValueError, UnicodeDecodeError):
            return
