"""Read-only Codex app-server usage adapter; never consumes reset credits or logs raw JSON."""

import asyncio
import json
import math
import os
import shutil
import signal
import stat
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from yoyackbot.codex_runner import persist_refreshed_auth

READ_METHOD = "account/rateLimits/read"
BUCKET_ID = "codex"
FIVE_HOUR_MINUTES = 300
WEEKLY_MINUTES = 10080
WARNING_PERCENT = 10
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_OUTPUT_BYTES = 256 * 1024
CLIENT_NAME = "yoyackbot"
USAGE_UNAVAILABLE_NOTICE = "🌫️ Codex 사용량을 지금 확인할 수 없소. 잠시 후 다시 시도하시오. 🙏"
USAGE_EXHAUSTED_NOTICE = "🪫 요약봇 사용량이 정상화되었소. 😵\n🙏 초기화의 가호가 함께하길... ✨"


class UsageUnavailable(RuntimeError):
    """Usage cannot be shown without guessing; the message never carries raw diagnostics."""


@dataclass(frozen=True)
class UsageSnapshot:
    """Remaining whole percent per window; None means the account reports no such window."""

    five_hour_remaining: int | None
    weekly_remaining: int | None

    @property
    def warning(self) -> bool:
        shown = [value for value in (self.five_hour_remaining, self.weekly_remaining)
                 if value is not None]
        return min(shown) <= WARNING_PERCENT


def remaining_percent(used: object) -> int:
    """Floor the remaining share so a displayed value never overstates what is left."""
    if isinstance(used, bool) or not isinstance(used, int | float):
        raise UsageUnavailable("usedPercent is not a number")
    if not math.isfinite(used) or not 0 <= used <= 100:
        raise UsageUnavailable("usedPercent is out of range")
    return math.floor(100 - used)


def _select_bucket(result: Mapping[str, object]) -> Mapping[str, object]:
    by_id = result.get("rateLimitsByLimitId")
    if by_id is not None:
        if not isinstance(by_id, Mapping):
            raise UsageUnavailable("rateLimitsByLimitId is malformed")
        bucket = by_id.get(BUCKET_ID)
        if isinstance(bucket, Mapping):
            return bucket
    single = result.get("rateLimits")
    if isinstance(single, Mapping) and single.get("limitId") == BUCKET_ID:
        return single
    raise UsageUnavailable("no explicitly matching codex bucket")


def parse_rate_limits(result: object) -> UsageSnapshot:
    """Pick the 5-hour and weekly windows by duration, never by primary/secondary order.

    An account may report only one of the two windows; any unknown duration is unavailable
    rather than shown under a guessed label.
    """
    if not isinstance(result, Mapping):
        raise UsageUnavailable("result is not an object")
    bucket = _select_bucket(result)
    windows: dict[int, int] = {}
    for key in ("primary", "secondary"):
        window = bucket.get(key)
        if window is None:
            continue
        if not isinstance(window, Mapping):
            raise UsageUnavailable("window is malformed")
        duration = window.get("windowDurationMins")
        if isinstance(duration, bool) or duration not in (FIVE_HOUR_MINUTES, WEEKLY_MINUTES):
            raise UsageUnavailable("unexpected window duration")
        if duration in windows:
            raise UsageUnavailable("duplicate window duration")
        windows[duration] = remaining_percent(window.get("usedPercent"))
    if not windows:
        raise UsageUnavailable("no usage window is reported")
    return UsageSnapshot(windows.get(FIVE_HOUR_MINUTES), windows.get(WEEKLY_MINUTES))


class _Session:
    def __init__(self, process: asyncio.subprocess.Process, max_output: int) -> None:
        self._process = process
        self._remaining = max_output
        self._next_id = 0

    async def send(self, message: Mapping[str, object]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message).encode() + b"\n")
        await self._process.stdin.drain()

    async def request(self, method: str, params: object) -> object:
        self._next_id += 1
        request_id = self._next_id
        await self.send({"id": request_id, "method": method, "params": params})
        while True:
            message = await self._read()
            if "method" in message:
                continue  # notifications and server requests are never usage
            if message.get("id") != request_id:
                continue
            if "error" in message or "result" not in message:
                raise UsageUnavailable(f"{method} returned an error")
            return message["result"]

    async def _read(self) -> Mapping[str, object]:
        assert self._process.stdout is not None
        try:
            line = await self._process.stdout.readuntil(b"\n")
        except asyncio.IncompleteReadError as error:
            raise UsageUnavailable("app-server closed its output") from error
        except asyncio.LimitOverrunError as error:
            raise UsageUnavailable("app-server line is too long") from error
        self._remaining -= len(line)
        if self._remaining < 0:
            raise UsageUnavailable("app-server output limit exceeded")
        try:
            message = json.loads(line)
        except ValueError as error:
            raise UsageUnavailable("app-server output is not JSON") from error
        if not isinstance(message, dict):
            raise UsageUnavailable("app-server message is not an object")
        return message


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def read_usage(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_output: int = MAX_OUTPUT_BYTES,
    client_version: str = "0",
) -> UsageSnapshot:
    """Run `codex app-server` over stdio, read usage once, and always reap the process group."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=dict(env),
            cwd=cwd,
            start_new_session=True,
            limit=max_output,
        )
    except OSError as error:
        raise UsageUnavailable("app-server could not start") from error
    session = _Session(process, max_output)

    async def exchange() -> UsageSnapshot:
        await session.request(
            "initialize",
            {"clientInfo": {"name": CLIENT_NAME, "version": client_version}},
        )
        await session.send({"method": "initialized"})
        result = await session.request(READ_METHOD, {"excludeResetCreditDetails": True})
        return parse_rate_limits(result)

    try:
        return await asyncio.wait_for(exchange(), timeout)
    except TimeoutError as error:
        raise UsageUnavailable("app-server timed out") from error
    except (OSError, ConnectionError) as error:
        raise UsageUnavailable("app-server pipe failed") from error
    finally:
        await _terminate(process)


def _private_file(path: Path) -> bool:
    try:
        info = path.lstat()
        directory = path.parent.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077
        and stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.geteuid()
        and not directory.st_mode & 0o077
    )


async def read_account_usage(
    executable: str,
    auth_file: Path,
    work_root: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client_version: str = "0",
) -> UsageSnapshot:
    """Read the bot account's usage from a disposable CODEX_HOME holding an auth copy.

    The app-server writes its own state files into CODEX_HOME, so it never receives the shared
    auth directory. A token refresh made during the read is kept only through the same
    compare-and-swap used by summaries.
    """
    if not Path(executable).is_absolute() or auth_file.name != "auth.json":
        raise UsageUnavailable("usage runtime is not configured")
    if not _private_file(auth_file):
        raise UsageUnavailable("auth file is not private")
    try:
        home = Path(tempfile.mkdtemp(prefix="request-usage-", dir=work_root))
    except OSError as error:
        raise UsageUnavailable("private work directory is unavailable") from error
    snapshot: bytes | None = None
    try:
        copied = home / "auth.json"
        try:
            snapshot = auth_file.read_bytes()
            descriptor = os.open(copied, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(snapshot)
        except OSError as error:
            raise UsageUnavailable("auth copy failed") from error
        env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CODEX_HOME": str(home),
               "LANG": "C.UTF-8"}
        return await read_usage(
            [executable, "app-server"], env=env, cwd=str(home), timeout=timeout,
            client_version=client_version,
        )
    finally:
        if snapshot is not None:
            persist_refreshed_auth(auth_file, home / "auth.json", snapshot)
        shutil.rmtree(home, ignore_errors=True)


def usage_message(snapshot: UsageSnapshot) -> str:
    """Show only the windows the account reports; warn when any shown window is at 10% or less."""
    lines = ["🔮✨ Codex의 기운을 살펴보았소. 👀", ""]
    if snapshot.five_hour_remaining is not None:
        lines.append(f"⏱️ 5시간 한도는 {snapshot.five_hour_remaining}% 남았소. 🔋")
    if snapshot.weekly_remaining is not None:
        lines.append(f"📅 주간 한도는 {snapshot.weekly_remaining}% 남았소. 🗓️")
    lines.append("")
    lines.append(
        "🟠⚠️ 요약 정상화가 버겁기 시작했소. 😰" if snapshot.warning
        else "🟢💪 아직 요약을 정상화하기엔 넉넉하오. 😎"
    )
    return "\n".join(lines)
