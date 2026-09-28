"""Safe entry point; the Discord gateway is added in 0.1.0."""

import argparse

from yoyackbot import __version__
from yoyackbot.config import ConfigurationError, Settings


def main() -> int:
    parser = argparse.ArgumentParser(prog="yoyackbot")
    parser.add_argument("command", choices=("version", "check-config", "run"))
    args = parser.parse_args()

    if args.command == "version":
        print(__version__)
        return 0

    try:
        Settings.from_environment()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}")
        return 2

    if args.command == "check-config":
        print("Configuration is valid")
        return 0

    print("Discord gateway is not implemented yet")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
