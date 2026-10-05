"""Bound resource use and remove private files after every process outcome."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from yoyackbot.codex import CodexContract, CodexFailure
from yoyackbot.codex_runner import CodexRunError, SandboxedCodex, _invoke
from yoyackbot.input_files import InputWorkspace, cleanup_stale_workspaces


def runner(tmp_path: Path, *, max_output_bytes: int = 200) -> SandboxedCodex:
    auth_dir = tmp_path / "model-auth"
    auth_dir.mkdir(mode=0o700)
    auth = auth_dir / "auth.json"
    auth.write_text("synthetic auth")
    auth.chmod(0o600)
    return SandboxedCodex(
        CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low"),
        auth, max_output_bytes=max_output_bytes,
    )


def test_oversized_stdout_is_stopped() -> None:
    with pytest.raises(CodexRunError) as raised:
        asyncio.run(_invoke(
            [sys.executable, "-c", "print('x' * 5_000_100)"], b"synthetic", os.environ.copy(),
            timeout=5, output_limit=100,
        ))
    assert raised.value.kind is CodexFailure.OUTPUT_LIMIT


def test_diagnostic_limit_cannot_be_raised_with_final_output_limit() -> None:
    with pytest.raises(CodexRunError) as raised:
        asyncio.run(_invoke(
            [sys.executable, "-c", "print('x' * 5_000_100)"], b"synthetic", os.environ.copy(),
            timeout=5, output_limit=10_000_000,
        ))
    assert raised.value.kind is CodexFailure.OUTPUT_LIMIT


def _child_state(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2]
    except (FileNotFoundError, ProcessLookupError):  # gone, or vanished while being read
        return None


def test_timeout_kills_parent_and_term_ignoring_child(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess,pathlib; "
        "child=subprocess.Popen(['/bin/bash','-c','trap \"\" TERM; exec sleep 60']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); child.wait()"
    )
    with pytest.raises(CodexRunError) as raised:
        asyncio.run(_invoke(
            [sys.executable, "-c", script], b"synthetic", os.environ.copy(),
            timeout=0.5, output_limit=200,
        ))
    assert raised.value.kind is CodexFailure.TIMEOUT
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        if _child_state(child_pid) in {None, "Z", "X"}:
            break
        time.sleep(0.05)
    assert _child_state(child_pid) in {None, "Z", "X"}


def test_cancelled_run_kills_child_process(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess,pathlib; "
        "child=subprocess.Popen(['/bin/bash','-c','trap \"\" TERM; exec sleep 60']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); child.wait()"
    )

    async def cancel() -> None:
        task = asyncio.create_task(_invoke(
            [sys.executable, "-c", script], b"synthetic", os.environ.copy(),
            timeout=10, output_limit=200,
        ))
        for _ in range(100):
            if pid_file.exists():
                break
            await asyncio.sleep(0.01)
        assert pid_file.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())
    assert _child_state(int(pid_file.read_text())) in {None, "Z", "X"}


def test_cancelled_model_call_removes_private_input_and_auth_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated = runner(tmp_path)
    entered = asyncio.Event()

    async def hanging_invoke(*_args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("yoyackbot.codex_runner._invoke", hanging_invoke)

    async def scenario() -> None:
        workspace = InputWorkspace.create(tmp_path / "inputs", b"synthetic only")
        task = asyncio.create_task(isolated.execute(workspace, "synthetic prompt"))
        await asyncio.wait_for(entered.wait(), 2)
        temporary_auth = workspace.directory / "auth" / "auth.json"
        assert temporary_auth.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert not workspace.directory.exists()

    asyncio.run(scenario())


def test_competing_refresh_cannot_overwrite_newer_shared_credentials(tmp_path: Path) -> None:
    isolated = runner(tmp_path)

    def auth(access: str, refresh: str) -> bytes:
        return json.dumps({"tokens": {"access_token": access, "refresh_token": refresh}}).encode()

    original = auth("access-1", "refresh-1")
    isolated.auth_file.write_bytes(original)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for path, data in ((first, auth("access-2", "refresh-2")),
                       (second, auth("access-stale", "refresh-stale"))):
        path.write_bytes(data)
        path.chmod(0o600)

    isolated._persist_refreshed_auth(first, original)
    assert isolated.auth_file.read_bytes() == first.read_bytes()
    isolated._persist_refreshed_auth(second, original)
    assert isolated.auth_file.read_bytes() == first.read_bytes()
    assert (isolated.auth_file.parent / ".auth-refresh.lock").stat().st_mode & 0o777 == 0o600

    current = isolated.auth_file.read_bytes()
    isolated._persist_refreshed_auth(second, current)
    assert isolated.auth_file.read_bytes() == second.read_bytes()


def test_invalid_refreshed_credentials_never_replace_shared_auth(tmp_path: Path) -> None:
    isolated = runner(tmp_path)
    original = b'{"tokens":{"access_token":"valid","refresh_token":"valid"}}'
    isolated.auth_file.write_bytes(original)
    candidate = tmp_path / "invalid.json"
    candidate.write_bytes(b'{"tokens":{}}')
    candidate.chmod(0o600)
    isolated._persist_refreshed_auth(candidate, original)
    assert isolated.auth_file.read_bytes() == original


def test_rejects_large_prompt_final_and_symlink_then_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = runner(tmp_path)
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        path = workspace.directory
        with pytest.raises(CodexRunError) as raised:
            asyncio.run(isolated.execute(workspace, "x" * (isolated.max_prompt_bytes + 1)))
        assert raised.value.kind is CodexFailure.INPUT_LIMIT
        assert not path.exists()

    async def success(
        _command: list[str], _prompt: bytes, _env: dict[str, str],
        _timeout: float, _limit: int,
    ) -> tuple[int, bytes, bytes]:
        return 0, b"", b""

    monkeypatch.setattr("yoyackbot.codex_runner._invoke", success)
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        path = workspace.directory
        (workspace.output_directory / "final.txt").write_bytes(b"x" * 201)
        with pytest.raises(CodexRunError) as raised:
            asyncio.run(isolated.execute(workspace, "small"))
        assert raised.value.kind is CodexFailure.OUTPUT_LIMIT
        assert not path.exists()

    canary = tmp_path / "outside.txt"
    canary.write_text("synthetic canary")
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        path = workspace.directory
        (workspace.output_directory / "final.txt").symlink_to(canary)
        with pytest.raises(CodexRunError) as raised:
            asyncio.run(isolated.execute(workspace, "small"))
        assert raised.value.kind is CodexFailure.PROCESS
        assert not path.exists()
    assert canary.read_text() == "synthetic canary"


def test_stale_cleanup_preserves_active_recent_and_unrelated_paths(tmp_path: Path) -> None:
    root = tmp_path / "inputs"
    stale = InputWorkspace.create(root, b"old")
    active = InputWorkspace.create(root, b"active")
    recent = InputWorkspace.create(root, b"recent")
    unrelated = root / "other-service"
    unrelated.mkdir()
    now = time.time()
    for directory in (stale.directory, active.directory, unrelated):
        os.utime(directory, (now - 7200, now - 7200))
    assert cleanup_stale_workspaces(
        root, older_than_seconds=3600, active=frozenset({active.directory}), now=now
    ) == 1
    assert not stale.directory.exists()
    assert active.log_file.exists() and recent.log_file.exists() and unrelated.exists()
    active.close()
    recent.close()
