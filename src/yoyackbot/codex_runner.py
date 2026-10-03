"""Run one Codex summary with only its input and final-output directory mounted."""

import asyncio
import fcntl
import json
import os
import pwd
import re
import signal
import stat
import tempfile
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path

from yoyackbot.codex import FAST_SERVICE_TIER, CodexContract, CodexFailure, classify_cli_failure
from yoyackbot.input_files import InputWorkspace

_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_DIAGNOSTIC_STREAM_LIMIT_BYTES = 5_000_000
# Set by the engine for one request of a server with `/속도 설정` on; every call reads it.
_FAST = ContextVar("yoyack_fast_tier", default=False)


class fast_tier:
    """Use the fast service tier for the Codex calls made inside this block."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    async def __aenter__(self) -> None:
        self._token = _FAST.set(self.enabled)

    async def __aexit__(self, *_exc: object) -> None:
        _FAST.reset(self._token)


class CodexRunError(RuntimeError):
    """Safe category; CLI stdout/stderr and conversation text are never retained."""

    def __init__(self, kind: CodexFailure) -> None:
        super().__init__(kind.value)
        self.kind = kind


class _OutputExceeded(RuntimeError):
    """Internal signal to stop a CLI that exceeds its output budget."""


async def _bounded_read(stream: asyncio.StreamReader, limit: int) -> bytes:
    """Drain verbose CLI diagnostics without retaining their private full text."""
    first = bytearray()
    tail = bytearray()
    total = 0
    while chunk := await stream.read(8192):
        total += len(chunk)
        if total > limit:
            raise _OutputExceeded
        if len(first) < 8192:
            first.extend(chunk[:8192 - len(first)])
        tail.extend(chunk)
        if len(tail) > 4096:
            del tail[:-4096]
    if total <= 8192:
        return bytes(first)
    return bytes(first[:4096] + tail)


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
        asyncio.create_task(_bounded_read(process.stdout, _DIAGNOSTIC_STREAM_LIMIT_BYTES)),
        asyncio.create_task(_bounded_read(process.stderr, _DIAGNOSTIC_STREAM_LIMIT_BYTES)),
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
        cli = replace(
            self.contract, executable="/bin/codex",
            service_tier=FAST_SERVICE_TIER if _FAST.get() else None,
        ).arguments(
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
        auth_snapshot: bytes | None = None
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
            try:
                auth_snapshot = self.auth_file.read_bytes()
                copied_auth.write_bytes(auth_snapshot)
            except OSError as exc:
                raise CodexRunError(CodexFailure.AUTH) from exc
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
            if temporary_auth is not None and auth_snapshot is not None:
                self._persist_refreshed_auth(temporary_auth / "auth.json", auth_snapshot)
            workspace.close()

    def _persist_refreshed_auth(self, candidate: Path, snapshot: bytes) -> None:
        persist_refreshed_auth(self.auth_file, candidate, snapshot)


def persist_refreshed_auth(auth_file: Path, candidate: Path, snapshot: bytes) -> None:
    """Keep only a valid refresh based on the current auth, even across processes."""
    lock_fd: int | None = None
    try:
        info = candidate.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            return
        updated = candidate.read_bytes()
        if updated == snapshot:
            return
        parsed = json.loads(updated)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("tokens"), dict):
            return
        tokens = parsed["tokens"]
        if not all(isinstance(tokens.get(key), str) and tokens[key] for key in (
            "access_token", "refresh_token",
        )):
            return
        lock_fd = os.open(
            auth_file.parent / ".auth-refresh.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600,
        )
        lock_info = os.fstat(lock_fd)
        if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
                or lock_info.st_mode & 0o077):
            return
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if auth_file.read_bytes() != snapshot:
            return
        fd, name = tempfile.mkstemp(prefix=".auth-update-", dir=auth_file.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(name, 0o600)
            os.replace(name, auth_file)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    except (OSError, ValueError, UnicodeDecodeError):
        return
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
