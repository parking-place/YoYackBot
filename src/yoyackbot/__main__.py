"""Command entry point with secret-safe failures."""

import argparse
import asyncio
import logging

import discord

from yoyackbot import __version__
from yoyackbot.config import ConfigurationError, Settings
from yoyackbot.discord import run_gateway


def main() -> int:
    parser = argparse.ArgumentParser(prog="yoyackbot")
    parser.add_argument("command", choices=("version", "check-config", "run"))
    parser.add_argument("--smoke-seconds", type=float)
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

    if args.smoke_seconds is not None and args.smoke_seconds <= 0:
        print("Gateway smoke duration must be positive")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(run_gateway(settings, smoke_seconds=args.smoke_seconds))
    except (discord.LoginFailure, discord.PrivilegedIntentsRequired):
        print("Gateway authentication or intent permission failed")
        return 2
    except (OSError, TimeoutError, discord.DiscordException):
        print("Gateway connection failed")
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
