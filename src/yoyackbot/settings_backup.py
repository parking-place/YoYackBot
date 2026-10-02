"""Settings-only recovery without retaining conversation records."""

import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore
from yoyackbot.summary_prompt import TONE_LIMIT
from yoyackbot.watch_store import SQLiteWatchStore, WatchStoreError

FORMAT = "yoyackbot-settings-v1"


class BackupError(RuntimeError):
    """Secret-safe settings backup or restore failure."""


def backup_settings(database: Path, backup_root: Path) -> Path:
    """Write only watch revisions, channels, cooldowns, manager roles and tones to a 0600 file."""
    if not database.is_file():
        raise BackupError("Settings database unavailable")
    try:
        with closing(sqlite3.connect(database, timeout=5)) as connection:
            connection.execute("BEGIN")
            if connection.execute("PRAGMA user_version").fetchone()[0] != 5:
                raise BackupError("Unsupported settings schema")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise BackupError("Settings database integrity failed")
            snapshot = {
                "format": FORMAT,
                "schema": 5,
                "watch_meta": connection.execute(
                    "SELECT guild_id, version FROM guild_watch_meta ORDER BY guild_id"
                ).fetchall(),
                "channels": connection.execute(
                    "SELECT guild_id, channel_id, updated_at FROM watched_channels "
                    "ORDER BY guild_id, channel_id"
                ).fetchall(),
                "cooldowns": connection.execute(
                    "SELECT guild_id, channel_id, last_success_us, expires_at_us "
                    "FROM summary_cooldowns ORDER BY guild_id, channel_id"
                ).fetchall(),
                **_manager_rows(connection),
                "tones": _tone_rows(connection),
            }
        backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if backup_root.is_symlink() or backup_root.stat().st_mode & 0o077:
            raise BackupError("Backup directory is not private")
        name = datetime.now(UTC).strftime("settings-%Y%m%dT%H%M%SZ-")
        name += secrets.token_hex(4) + ".json"
        target = backup_root / name
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(snapshot, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target
    except (OSError, sqlite3.Error) as exc:
        raise BackupError("Settings backup failed") from exc


def _manager_rows(connection: sqlite3.Connection) -> dict[str, list[tuple[int, ...]]]:
    """Manager roles (1.1.3) live in optional tables; older databases simply have none."""
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('manager_role_meta', 'manager_roles')"
        )
    }
    if tables != {"manager_role_meta", "manager_roles"}:
        return {"manager_meta": [], "manager_roles": []}
    return {
        "manager_meta": connection.execute(
            "SELECT guild_id, version FROM manager_role_meta ORDER BY guild_id"
        ).fetchall(),
        "manager_roles": connection.execute(
            "SELECT guild_id, role_id, updated_at FROM manager_roles ORDER BY guild_id, role_id"
        ).fetchall(),
    }


def _tone_rows(connection: sqlite3.Connection) -> list[list[object]]:
    """Server tones (1.3.0) are settings; older databases have no table."""
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='guild_tones'"
    ).fetchone() is None:
        return []
    return [list(row) for row in connection.execute(
        "SELECT guild_id, version, content, updated_us FROM guild_tones ORDER BY guild_id"
    )]


def _validated_tones(data: dict) -> list[tuple[int, int, str | None, int]]:
    rows = data.get("tones", [])
    if not isinstance(rows, list):
        raise BackupError("Settings backup is invalid")
    valid = []
    for row in rows:
        if (
            not isinstance(row, list) or len(row) != 4
            or type(row[0]) is not int or row[0] < 1 or type(row[1]) is not int or row[1] < 0
            or type(row[3]) is not int or row[3] < 0
            or not (row[2] is None or (isinstance(row[2], str) and 0 < len(row[2]) <= TONE_LIMIT))
        ):
            raise BackupError("Settings backup is invalid")
        valid.append((row[0], row[1], row[2], row[3]))
    return valid


def _validated_rows(data: object, key: str, columns: int) -> list[tuple[int, ...]]:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise BackupError("Settings backup is invalid")
    rows: list[tuple[int, ...]] = []
    for row in data[key]:
        if not isinstance(row, list) or len(row) != columns:
            raise BackupError("Settings backup is invalid")
        if any(type(value) is not int or value < 0 for value in row):
            raise BackupError("Settings backup is invalid")
        if row[0] < 1 or (columns > 2 and row[1] < 1):
            raise BackupError("Settings backup is invalid")
        rows.append(tuple(row))
    return rows


def restore_settings(
    backup: Path, target: Path, *, live_database: Path, retention_days: int = 30,
) -> None:
    """Create an isolated schema-5 database with an empty message cache."""
    if not 1 <= retention_days <= 30:
        raise BackupError("Restore retention policy is invalid")
    if target.resolve() == live_database.resolve() or target.exists() or target.is_symlink():
        raise BackupError("Restore target must be a new isolated database")
    try:
        if backup.stat().st_mode & 0o077:
            raise BackupError("Settings backup is not private")
        data = json.loads(backup.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("schema") != 5:
            raise BackupError("Settings backup is invalid")
        meta = _validated_rows(data, "watch_meta", 2)
        channels = _validated_rows(data, "channels", 3)
        cooldowns = _validated_rows(data, "cooldowns", 4)
        # Backups made before 1.1.3 have no manager roles.
        manager_meta = _validated_rows(data, "manager_meta", 2) if "manager_meta" in data else []
        manager_roles = (
            _validated_rows(data, "manager_roles", 3) if "manager_roles" in data else []
        )
        tones = _validated_tones(data)  # backups made before 1.3.0 have none
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        try:
            SQLiteWatchStore(target)
            with closing(sqlite3.connect(target, timeout=5)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "INSERT INTO guild_watch_meta(guild_id, version) VALUES (?, ?)", meta
                )
                connection.executemany(
                    "INSERT INTO watched_channels(guild_id, channel_id, updated_at) "
                    "VALUES (?, ?, ?)", channels,
                )
                connection.executemany(
                    "INSERT INTO summary_cooldowns(guild_id, channel_id, "
                    "last_success_us, expires_at_us) VALUES (?, ?, ?, ?)", cooldowns,
                )
                connection.executemany(
                    "INSERT INTO manager_role_meta(guild_id, version) VALUES (?, ?)", manager_meta
                )
                connection.executemany(
                    "INSERT INTO manager_roles(guild_id, role_id, updated_at) VALUES (?, ?, ?)",
                    manager_roles,
                )
                connection.executemany(
                    "INSERT INTO guild_tones(guild_id, version, content, updated_us) "
                    "VALUES (?, ?, ?, ?)", tones,
                )
                connection.commit()
            SQLiteMessageStore(target).prune_before(
                datetime.now(UTC) - timedelta(days=retention_days)
            )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    except (OSError, sqlite3.Error, ValueError, TypeError, WatchStoreError,
            MessageStoreError, json.JSONDecodeError) as exc:
        raise BackupError("Settings restore failed") from exc
