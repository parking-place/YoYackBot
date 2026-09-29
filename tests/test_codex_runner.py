"""The model process receives one request file and only its final model message escapes."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from yoyackbot.codex import CodexContract, CodexFailure
from yoyackbot.codex_runner import (
    CodexRunError,
    SandboxedCodex,
    _bounded_read,
    _OutputExceeded,
    final_text,
)
from yoyackbot.input_files import InputWorkspace


def runner(tmp_path: Path) -> SandboxedCodex:
    auth_dir = tmp_path / "model-auth"
    auth_dir.mkdir(mode=0o700)
    auth = auth_dir / "auth.json"
    auth.write_text("synthetic credential fixture")
    auth.chmod(0o600)
    return SandboxedCodex(
        CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low"), auth,
    )


def test_mounts_only_request_input_output_and_auth(tmp_path: Path) -> None:
    isolated = runner(tmp_path)
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        args = isolated.command(workspace)
        assert args[:2] == ["/usr/bin/bwrap", "--die-with-parent"]
        assert ["--ro-bind", str(workspace.log_file), "/work/conversation.jsonl"] == args[
            args.index(str(workspace.log_file)) - 1:args.index(str(workspace.log_file)) + 2
        ]
        assert ["--bind", str(workspace.output_directory), "/output"] == args[
            args.index(str(workspace.output_directory)) - 1:
            args.index(str(workspace.output_directory)) + 2
        ]
        assert "--tmpfs" in args and "--unshare-all" in args
        assert "--ephemeral" in args and "--ignore-user-config" in args
        assert ["--bind", str(isolated.auth_file.parent), "/auth"] == args[
            args.index(str(isolated.auth_file.parent)) - 1:
            args.index(str(isolated.auth_file.parent)) + 2
        ]
        assert 'web_search="disabled"' in args
        assert 'default_permissions="summary-read"' in args
        assert '"/auth"="deny"' in " ".join(args)
        assert "--sandbox" not in args


def test_auth_symlink_or_shared_credentials_are_refused(tmp_path: Path) -> None:
    isolated = runner(tmp_path)
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        isolated.auth_file.chmod(0o644)
        with pytest.raises(CodexRunError):
            isolated.command(workspace)
        isolated.auth_file.chmod(0o600)
        link_dir = tmp_path / "linked-auth"
        link_dir.mkdir(mode=0o700)
        link = link_dir / "auth.json"
        link.symlink_to(isolated.auth_file)
        with pytest.raises(CodexRunError):
            SandboxedCodex(isolated.contract, link).command(workspace)


def test_only_final_file_is_returned_and_discord_environment_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = runner(tmp_path)
    received: dict[str, object] = {}

    async def fake_invoke(
        command: list[str], prompt: bytes, env: dict[str, str], _timeout: float, _limit: int
    ) -> tuple[int, bytes, bytes]:
        received["prompt"] = prompt
        received["argv"] = command
        received["env"] = env
        return 0, b"progress event that must not be posted", b"diagnostic"

    monkeypatch.setattr("yoyackbot.codex_runner._invoke", fake_invoke)
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        (workspace.output_directory / "final.txt").write_bytes(b"\x1b[31mFinal only\x1b[0m\n")
        result = asyncio.run(isolated.execute(workspace, "private conversation prompt"))
        assert result == "Final only"
        assert received["prompt"] == b"private conversation prompt"
        assert "private conversation prompt" not in received["argv"]
        assert "DISCORD_BOT_TOKEN" not in received["env"]


def test_failure_never_surfaces_raw_cli_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = runner(tmp_path)

    async def fake_invoke(
        _command: list[str], _prompt: bytes, _env: dict[str, str],
        _timeout: float, _limit: int,
    ) -> tuple[int, bytes, bytes]:
        return 1, b"", b"authentication failed: secret-bearing text"

    monkeypatch.setattr("yoyackbot.codex_runner._invoke", fake_invoke)
    with (
        InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace,
        pytest.raises(CodexRunError) as raised,
    ):
        asyncio.run(isolated.execute(workspace, "synthetic prompt"))
    assert raised.value.kind is CodexFailure.AUTH
    assert "secret-bearing" not in str(raised.value)


def test_empty_or_non_utf8_final_is_rejected() -> None:
    with pytest.raises(CodexRunError):
        final_text(b"\x1b[31m\x1b[0m")
    with pytest.raises(CodexRunError):
        final_text(b"\xff")


def test_verbose_cli_stream_is_drained_but_only_small_sample_is_retained() -> None:
    async def scenario() -> None:
        stream = asyncio.StreamReader()
        stream.feed_data(b"A" * 4096 + b"B" * 200_000 + b"C" * 4096)
        stream.feed_eof()
        sample = await _bounded_read(stream, 5_000_000)
        assert len(sample) == 8192
        assert sample.startswith(b"A" * 4096)
        assert sample.endswith(b"C" * 4096)

        excessive = asyncio.StreamReader()
        excessive.feed_data(b"X" * 10_001)
        excessive.feed_eof()
        with pytest.raises(_OutputExceeded):
            await _bounded_read(excessive, 10_000)

    asyncio.run(scenario())


def test_final_message_limit_still_applies_after_verbose_cli_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated = replace(runner(tmp_path), max_output_bytes=100)

    async def fake_invoke(
        _command: list[str], _prompt: bytes, _env: dict[str, str],
        _timeout: float, _limit: int,
    ) -> tuple[int, bytes, bytes]:
        (workspace.output_directory / "final.txt").write_bytes(b"A" * 101)
        return 0, b"", b""

    monkeypatch.setattr("yoyackbot.codex_runner._invoke", fake_invoke)
    with (
        InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace,
        pytest.raises(CodexRunError) as raised,
    ):
        asyncio.run(isolated.execute(workspace, "synthetic prompt"))
    assert raised.value.kind is CodexFailure.OUTPUT_LIMIT


def test_auth_refresh_persists_without_cli_state_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = runner(tmp_path)
    before = '{"tokens":{"access_token":"synthetic-before","refresh_token":"refresh-before"}}'
    after = '{"tokens":{"access_token":"synthetic-after","refresh_token":"refresh-after"}}'
    isolated.auth_file.write_text(before)
    seen: dict[str, Path] = {}

    async def fake_invoke(
        command: list[str], _prompt: bytes, _env: dict[str, str],
        _timeout: float, _limit: int,
    ) -> tuple[int, bytes, bytes]:
        bound = next(Path(command[index + 1]) for index, token in enumerate(command[:-2])
                     if token == "--bind" and command[index + 2] == "/auth")
        seen["temporary_auth"] = bound
        (bound / "auth.json").write_text(after)
        (bound / "session-state").write_text("temporary-only")
        (workspace.output_directory / "final.txt").write_text("완료하였소.")
        return 0, b"", b""

    monkeypatch.setattr("yoyackbot.codex_runner._invoke", fake_invoke)
    with InputWorkspace.create(tmp_path / "inputs", b"synthetic") as workspace:
        directory = workspace.directory
        assert asyncio.run(isolated.execute(workspace, "synthetic prompt")) == "완료하였소."
    assert isolated.auth_file.read_text() == after
    assert not directory.exists() and not seen["temporary_auth"].exists()
    assert {path.name for path in isolated.auth_file.parent.iterdir()} == {
        "auth.json", ".auth-refresh.lock",
    }
