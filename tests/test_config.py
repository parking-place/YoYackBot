"""Check that missing and present secrets never enter CLI output."""

import os
import subprocess
import sys

import pytest

from yoyackbot.config import ConfigurationError, Settings


def invoke(command: str, token: str | None, *options: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DISCORD_BOT_TOKEN", None)
    env.pop("DISCORD_BOT_TOKEN_FILE", None)
    if token is not None:
        env["DISCORD_BOT_TOKEN"] = token
    return subprocess.run(
        [sys.executable, "-m", "yoyackbot", command, *options],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_config_check_without_secret_names_missing_setting_only() -> None:
    result = invoke("check-config", None)
    assert result.returncode == 2
    assert result.stdout.strip() == "Configuration error: Discord bot credential is not set"
    assert result.stderr == ""


def test_config_check_with_secret_never_prints_value() -> None:
    fake_secret = "only-a-test-secret-value"
    result = invoke("check-config", fake_secret)
    assert result.returncode == 0
    assert "Configuration is valid" in result.stdout
    assert fake_secret not in result.stdout + result.stderr


def test_invalid_smoke_duration_rejects_before_network_access() -> None:
    result = invoke("run", "only-a-test-secret-value", "--smoke-seconds", "0")
    assert result.returncode == 2
    assert "Gateway smoke duration must be positive" in result.stdout


def test_private_credential_file_precedes_environment_token(tmp_path) -> None:
    file = tmp_path / "discord-token"
    file.write_text("only-a-test-file-token\n")
    file.chmod(0o600)
    values = {
        "DISCORD_BOT_TOKEN_FILE": str(file),
        "DISCORD_BOT_TOKEN": "only-a-test-env-token",
    }
    settings = Settings.from_environment(values)
    assert settings.discord_bot_token == "only-a-test-file-token"
    assert "only-a-test-file-token" not in repr(settings)
    file.chmod(0o644)
    with pytest.raises(ConfigurationError) as raised:
        Settings.from_environment(values)
    assert "only-a-test-file-token" not in str(raised.value)


def test_systemd_credential_copy_precedes_manual_file(tmp_path) -> None:
    directory = tmp_path / "credentials"
    directory.mkdir()
    copied = directory / "discord_token"
    copied.write_text("only-a-test-systemd-token")
    copied.chmod(0o444)
    settings = Settings.from_environment({
        "CREDENTIALS_DIRECTORY": str(directory),
        "DISCORD_BOT_TOKEN_FILE": "/missing/manual-token",
    })
    assert settings.discord_bot_token == "only-a-test-systemd-token"


def test_model_queue_default_waits_longer_than_model_timeout() -> None:
    settings = Settings.from_environment({"DISCORD_BOT_TOKEN": "only-a-test-token"})
    assert settings.codex_timeout_seconds == 120
    assert settings.queue_wait_seconds == 180
