"""Secret-safe local preflight before accepting Discord work."""

import sqlite3
from enum import Enum

from yoyackbot.codex import CodexContract, CodexContractError
from yoyackbot.config import Settings
from yoyackbot.input_files import InputFileError, InputWorkspace
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError


class ReadinessKind(Enum):
    MODEL = "model runtime or authentication unavailable"
    DATABASE = "settings database unavailable"
    INPUT = "private request directory unavailable"


class ReadinessError(RuntimeError):
    def __init__(self, kind: ReadinessKind) -> None:
        super().__init__(kind.value)
        self.kind = kind


def check_ready(settings: Settings) -> None:
    """Check only local resources; gateway readiness is observed after connection."""
    try:
        contract = CodexContract.from_settings(settings)
    except CodexContractError as exc:
        raise ReadinessError(ReadinessKind.MODEL) from exc
    if (
        not contract.version_matches()
        or not contract.authentication_ready(settings.codex_auth_directory)
    ):
        raise ReadinessError(ReadinessKind.MODEL)

    try:
        SQLiteWatchStore(settings.database_path)
        with sqlite3.connect(settings.database_path, timeout=5) as connection:
            connection.execute("BEGIN IMMEDIATE")
            healthy = connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            connection.rollback()
        if not healthy or version != 5:
            raise ReadinessError(ReadinessKind.DATABASE)
    except (OSError, sqlite3.Error, WatchStoreError) as exc:
        raise ReadinessError(ReadinessKind.DATABASE) from exc

    try:
        workspace = InputWorkspace.create(settings.input_directory.absolute(), b"preflight")
        workspace.close()
    except (OSError, InputFileError) as exc:
        raise ReadinessError(ReadinessKind.INPUT) from exc
