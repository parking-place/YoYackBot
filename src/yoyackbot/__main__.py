"""Command entry point with secret-safe failures."""

import argparse
import asyncio
import json
import logging

import discord

from yoyackbot import __version__
from yoyackbot.config import ConfigurationError, Settings
from yoyackbot.discord import run_gateway
from yoyackbot.health import read_heartbeat
from yoyackbot.input_files import GatewayAlreadyRunning, InputFileError
from yoyackbot.readiness import ReadinessError, ReadinessKind, check_ready
from yoyackbot.watch_store import WatchStoreError


def main() -> int:
    parser = argparse.ArgumentParser(prog="yoyackbot")
    parser.add_argument("command", choices=("version", "check-config", "check-ready", "health", "run"))
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

    if args.command == "check-ready":
        try:
            check_ready(settings)
        except ReadinessError as exc:
            print(f"Readiness failed: {exc.kind.value}")
            return 2
        print("Local resources are ready")
        return 0

    if args.command == "health":
        process_alive, gateway_ready = read_heartbeat(settings.input_directory)
        local_ready, auth_attention = True, False
        try:
            check_ready(settings)
        except ReadinessError as exc:
            local_ready = False
            auth_attention = exc.kind is ReadinessKind.MODEL
        print(json.dumps({
            "process_alive": process_alive,
            "gateway_ready": gateway_ready,
            "local_ready": local_ready,
            "ready": process_alive and gateway_ready and local_ready,
            "model_auth_attention": auth_attention,
        }, sort_keys=True))
        return 0 if process_alive and gateway_ready and local_ready else 2

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
