"""The CLI boundary keeps private input out of process arguments and error records."""

from dataclasses import replace
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from yoyackbot.codex import (
    CodexContract,
    CodexContractError,
    CodexFailure,
    classify_cli_failure,
)
from yoyackbot.config import Settings


def contract() -> CodexContract:
    settings = Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic", "YOYACK_CODEX_EXECUTABLE": "/synthetic/bin/codex",
    })
    return CodexContract.from_settings(settings)


@pytest.mark.parametrize(
    ("model", "effort"),
    [("other-model", "low"), ("gpt-6-luna", "medium")],
)
def test_required_model_and_reasoning_are_fixed(model: str, effort: str) -> None:
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "synthetic"})
    with pytest.raises(CodexContractError):
        CodexContract.from_settings(
            replace(settings, codex_model=model, codex_reasoning_effort=effort)
        )


def test_arguments_use_stdin_and_isolated_ephemeral_execution(tmp_path: Path) -> None:
    args = contract().arguments(
        working_directory=tmp_path,
        output_file=tmp_path / "final.txt",
    )
    assert args[-1] == "-"
    assert "--model" in args and args[args.index("--model") + 1] == "gpt-6-luna"
    assert "model_reasoning_effort=low" in args
    for option in ("--sandbox", "read-only", "--ephemeral", "--ignore-user-config",
                   "--ignore-rules", "--output-last-message"):
        assert option in args


def test_relative_working_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        contract().arguments(working_directory=Path("relative"), output_file=tmp_path / "out")


def test_version_and_authentication_probe_do_not_retain_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(args)
        if args[-1] == "--version":
            return CompletedProcess(args, 0, "codex-cli 0.158.0\n", "")
        return CompletedProcess(args, 1, "", "secret-bearing diagnostic")

    monkeypatch.setattr("yoyackbot.codex.subprocess.run", fake_run)
    instance = contract()
    assert instance.version_matches()
    assert not instance.authentication_ready()
    assert calls == [["/synthetic/bin/codex", "--version"],
                     ["/synthetic/bin/codex", "login", "status"]]


def test_dedicated_auth_probe_is_read_only_and_checks_file_permissions(tmp_path: Path) -> None:
    directory = tmp_path / "model-auth"
    directory.mkdir(mode=0o700)
    auth = directory / "auth.json"
    auth.write_text('{"synthetic":"value"}')
    auth.chmod(0o600)
    assert contract().authentication_ready(directory)
    assert {path.name for path in directory.iterdir()} == {"auth.json"}
    auth.chmod(0o644)
    assert not contract().authentication_ready(directory)
    auth.chmod(0o600)
    auth.write_text("not JSON")
    assert not contract().authentication_ready(directory)


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("model_not_found: private", CodexFailure.MODEL),
        ("Failed to refresh token: private", CodexFailure.AUTH),
        ("HTTP 429 private", CodexFailure.LIMIT),
        ("unexpected: private", CodexFailure.PROCESS),
    ],
)
def test_failure_category_never_contains_raw_diagnostic(
    diagnostic: str, expected: CodexFailure
) -> None:
    result = classify_cli_failure(1, diagnostic)
    assert result is expected
    assert "private" not in result.value
    assert classify_cli_failure(0, diagnostic) is None
