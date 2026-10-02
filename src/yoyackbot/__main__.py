"""Command entry point with secret-safe failures."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

import discord

from yoyackbot import __version__
from yoyackbot.config import ConfigurationError, Settings
from yoyackbot.discord import run_gateway
from yoyackbot.health import COLLECTION_OK, read_heartbeat_details
from yoyackbot.input_files import GatewayAlreadyRunning, InputFileError
from yoyackbot.manager_roles import SQLiteManagerRoleStore
from yoyackbot.readiness import ReadinessError, ReadinessKind, check_ready
from yoyackbot.settings_backup import BackupError, backup_settings, restore_settings
from yoyackbot.watch_store import WatchStoreError

MANAGER_ROLES_USAGE = (
    "Usage: manager-roles list GUILD_ID | set GUILD_ID ROLE_ID [ROLE_ID ...] | clear GUILD_ID"
)


def manager_roles_command(settings: Settings, words: list[str]) -> int:
    """Operator-only view and recovery of a server's bot manager roles (1.1.3)."""
    try:
        action, guild_id, *role_ids = words[0], int(words[1]), *(int(word) for word in words[2:])
    except (IndexError, ValueError):
        print(MANAGER_ROLES_USAGE)
        return 2
    if action not in {"list", "set", "clear"} or guild_id < 1 or any(role < 1 for role in role_ids) \
            or (action == "set") != bool(role_ids):
        print(MANAGER_ROLES_USAGE)
        return 2
    try:
        store = SQLiteManagerRoleStore(settings.database_path)
        if action != "list":
            store.replace(guild_id, frozenset(role_ids))
        roles = sorted(store.get(guild_id))
    except (WatchStoreError, ValueError):
        print("Manager role settings are unavailable")
        return 2
    print(f"Manager roles: {len(roles)}" + (": " + " ".join(map(str, roles)) if roles else ""))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="yoyackbot")
    parser.add_argument("command", choices=(
        "version", "check-config", "check-ready", "health", "backup-settings",
        "restore-settings", "manager-roles", "run",
    ))
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--smoke-seconds", type=float)
    parser.add_argument("--observe-channel-id", type=int)
    args = parser.parse_args()

    if args.command == "version":
        print(__version__)
        return 0

    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}")
        return 2

    if args.command == "check-config":
        print("Configuration is valid")
        return 0

    if args.command == "backup-settings":
        if args.paths:
            print("Settings backup takes no path; it uses the private backup directory")
            return 2
        try:
            backup_settings(settings.database_path, settings.database_path.parent / "backups")
        except BackupError:
            print("Settings backup failed")
            return 2
        print("Settings-only backup created in the private backup directory")
        return 0

    if args.command == "restore-settings":
        if len(args.paths) != 2:
            print("Restore requires a private backup file and a new isolated database path")
            return 2
        try:
            restore_settings(
                Path(args.paths[0]), Path(args.paths[1]), live_database=settings.database_path,
                retention_days=settings.cache_retention_days,
            )
        except BackupError:
            print("Settings restore failed")
            return 2
        print("Settings restored into an isolated database with an empty message cache")
        return 0

    if args.command == "manager-roles":
        return manager_roles_command(settings, args.paths)

    if args.command == "check-ready":
        try:
            check_ready(settings)
        except ReadinessError as exc:
            print(f"Readiness failed: {exc.kind.value}")
            return 2
        print("Local resources are ready")
        return 0

    if args.command == "health":
        process_alive, gateway_ready, worker = read_heartbeat_details(settings.input_directory)
        collecting = worker in COLLECTION_OK
        local_ready, auth_attention = True, False
        try:
            check_ready(settings)
        except ReadinessError as exc:
            local_ready = False
            auth_attention = exc.kind is ReadinessKind.MODEL
        print(json.dumps({
            "process_alive": process_alive,
            "gateway_ready": gateway_ready,
            "collection_worker": worker or "unknown",
            "local_ready": local_ready,
            "ready": process_alive and gateway_ready and collecting and local_ready,
            "model_auth_attention": auth_attention,
        }, sort_keys=True))
        return 0 if process_alive and gateway_ready and collecting and local_ready else 2

    if args.smoke_seconds is not None and args.smoke_seconds <= 0:
        print("Gateway smoke duration must be positive")
        return 2
    if args.observe_channel_id is not None and args.smoke_seconds is None:
        print("Channel observation is available only in smoke mode")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("discord").setLevel(logging.ERROR)
    try:
        asyncio.run(
            run_gateway(
                settings,
                smoke_seconds=args.smoke_seconds,
                observe_channel_id=args.observe_channel_id,
            )
        )
    except (discord.LoginFailure, discord.PrivilegedIntentsRequired):
        print("Gateway authentication or intent permission failed")
        return 2
    except (OSError, TimeoutError, discord.DiscordException):
        print("Gateway connection failed")
        return 2
    except WatchStoreError:
        print("Watched-channel settings database is unavailable")
        return 2
    except GatewayAlreadyRunning:
        print("Gateway already running for this runtime directory")
        return 2
    except InputFileError:
        print("Private runtime directory is unavailable")
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
