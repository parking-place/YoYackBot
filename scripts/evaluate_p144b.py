"""T144b-P1-B: the 1.4.4-P4 evaluation (daily tally, weekly advice) with each CLI run's model.

Runs `evaluate_p144` unchanged and prints `invoke model=…` to stderr for every Codex CLI run, so
the report shows which model actually answered; warnings (e.g. a model fallback) go to stderr too.
LXC only; nothing is posted.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_p144

from yoyackbot import codex_runner

_invoke = codex_runner._invoke


async def recorded(command, *args, **kwargs):
    print("invoke model=" + command[command.index("--model") + 1], file=sys.stderr, flush=True)
    return await _invoke(command, *args, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("which", choices=("all", "daily", "weekly"))
    parser.add_argument("tones", nargs="*")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(message)s")
    codex_runner._invoke = recorded
    asyncio.run(evaluate_p144.main_async(args.which, args.tones or ["default", "mz", "tsundere"]))


if __name__ == "__main__":
    main()
