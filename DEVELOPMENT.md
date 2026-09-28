# Development baseline

Runtime target: Python 3.13.5 on Debian 13 x86_64 in the provided LXC. `discord.py` is pinned to 2.7.1. The remaining exact transitive versions are captured in `requirements.lock` after installation in the LXC.

The package currently provides `version`, `check-config`, and a `run` entry point that explicitly reports the gateway as unavailable. Subsequent stages implement the gateway and summary flow. Current source completion is tracked in [STATUS](Plans/0.DevelopPhase/STATUS.md).

Create an isolated virtual environment and install the lock file with `pip install -r requirements.lock`, followed by `pip install --no-deps -e .`. Run `pytest` and `ruff check src tests` in the development LXC. Keep credentials out of shell history, repository files, test output, and CI artifacts. `check-config` names missing settings without printing supplied values.

On the provided LXC, the isolated development checkout is `/opt/yoyackbot-dev`. It is not the final service path; the service, privileges, and runtime data location will be finalized in 0.8.0. No product version is ready for deployment at this stage.
