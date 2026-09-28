"""Check that missing and present secrets never enter CLI output."""

import os
import subprocess
import sys


def invoke(command: str, token: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DISCORD_BOT_TOKEN", None)
    if token is not None:
        env["DISCORD_BOT_TOKEN"] = token
    return subprocess.run(
        [sys.executable, "-m", "yoyackbot", command],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_config_check_without_secret_names_missing_setting_only() -> None:
    result = invoke("check-config", None)
    assert result.returncode == 2
    assert result.stdout.strip() == "Configuration error: DISCORD_BOT_TOKEN is not set"
    assert result.stderr == ""


def test_config_check_with_secret_never_prints_value() -> None:
    fake_secret = "only-a-test-secret-value"
    result = invoke("check-config", fake_secret)
    assert result.returncode == 0
    assert "Configuration is valid" in result.stdout
    assert fake_secret not in result.stdout + result.stderr


def test_run_is_explicitly_unavailable_until_gateway_stage() -> None:
    result = invoke("run", "only-a-test-secret-value")
    assert result.returncode == 2
    assert "not implemented yet" in result.stdout
