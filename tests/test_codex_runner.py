"""The model process receives one request file and only its final model message escapes."""

import asyncio
from pathlib import Path

import pytest

from yoyackbot.codex import CodexContract, CodexFailure
from yoyackbot.codex_runner import CodexRunError, SandboxedCodex, final_text
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
        assert ["--bind", str(workspace.directory), "/output"] == args[
            args.index(str(workspace.directory)) - 1:args.index(str(workspace.directory)) + 2
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
        (workspace.directory / "final.txt").write_bytes(b"\x1b[31mFinal only\x1b[0m\n")
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
