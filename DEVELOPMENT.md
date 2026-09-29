# Development baseline

Runtime target: Python 3.13.5 on Debian 13 x86_64 in the provided LXC. `discord.py` is pinned to 2.7.1. The remaining exact transitive versions are captured in `requirements.lock` after installation in the LXC.

The package provides `version`, `check-config`, and a `run` Gateway entry point. Set `YOYACK_DEV_GUILD_ID` in the development environment to register `/채널 설정` immediately in the test Guild. Without it, the command is registered globally and may take longer to appear. Set `YOYACK_DB_PATH` to a writable private location outside the repository; the settings database is created with mode `0600`. Current source completion is tracked in [STATUS](Plans/0.DevelopPhase/STATUS.md).

Create an isolated virtual environment and install the lock file with `pip install -r requirements.lock`, followed by `pip install --no-deps -e .`. Run `pytest` and `ruff check src tests` in the development LXC. Keep credentials out of shell history, repository files, test output, and CI artifacts. `check-config` names missing settings without printing supplied values.

On the provided LXC, the development checkout is `/opt/yoyackbot-dev`. A dedicated `systemd` service, account, and private runtime data path were established in 0.8.0; see [service operations](docs/service-operations.md). The user selected in-place promotion of this LXC and bot account for 1.0.0. Follow the [release install guide](docs/install-release.md) and its staged validation before deployment or tagging.
