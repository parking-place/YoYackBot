"""Local service preflight refuses unsafe resources without exposing values."""

import sqlite3

import pytest

from yoyackbot.codex import CodexContract
from yoyackbot.config import Settings
from yoyackbot.readiness import ReadinessError, ReadinessKind, check_ready
from yoyackbot.watch_store import WatchStoreError


def settings(tmp_path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic-only",
        "YOYACK_DB_PATH": str(tmp_path / "db" / "messages.db"),
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "private-input"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "fake-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/synthetic/codex",
    })


def ready_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CodexContract, "executable_problem", lambda _self: None)
    monkeypatch.setattr(CodexContract, "version_matches", lambda _self: True)
    monkeypatch.setattr(CodexContract, "authentication_ready", lambda _self, _auth: True)


def test_preflight_checks_writable_database_and_leaves_no_request_files(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_model(monkeypatch)
    config = settings(tmp_path)
    check_ready(config)
    with sqlite3.connect(config.database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
    assert config.input_directory.is_dir()
    assert list(config.input_directory.iterdir()) == []


def test_model_or_database_failure_stops_before_gateway_start(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = settings(tmp_path)
    monkeypatch.setattr(CodexContract, "executable_problem", lambda _self: None)
    monkeypatch.setattr(CodexContract, "version_matches", lambda _self: False)
    with pytest.raises(ReadinessError) as model:
        check_ready(config)
    assert model.value.kind is ReadinessKind.MODEL
    assert not config.database_path.exists()

    ready_model(monkeypatch)

    def broken_store(_path):
        raise WatchStoreError("synthetic permission denial")

    monkeypatch.setattr("yoyackbot.readiness.SQLiteWatchStore", broken_store)
    with pytest.raises(ReadinessError) as database:
        check_ready(config)
    assert database.value.kind is ReadinessKind.DATABASE
    assert "synthetic permission denial" not in str(database.value)


def test_shared_input_directory_is_rejected_after_database_check(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_model(monkeypatch)
    config = settings(tmp_path)
    config.input_directory.mkdir(mode=0o755)
    config.input_directory.chmod(0o755)
    with pytest.raises(ReadinessError) as input_error:
        check_ready(config)
    assert input_error.value.kind is ReadinessKind.INPUT
    assert config.database_path.exists()
