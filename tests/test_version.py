"""Keep the shipped CLI version aligned with source distribution metadata."""

import tomllib
from pathlib import Path

from yoyackbot import __version__


def test_source_and_package_versions_match() -> None:
    root = Path(__file__).resolve().parents[1]
    declared = (root / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert declared == project["project"]["version"] == __version__ == "1.0.0.4"
