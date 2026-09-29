"""Check plan navigation, stage accounting, and public tree boundaries."""

import re
import subprocess
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / "Plans/0.DevelopPhase"
VERSIONS = [f"0.{number}.0" for number in range(10)] + ["1.0.0"]


def main() -> None:
    directories = sorted(
        path.name
        for path in PLAN.iterdir()
        if path.is_dir() and re.fullmatch(r"(?:0\.[0-9]\.0|1\.0\.0)", path.name)
    )
    assert directories == VERSIONS, "version directories differ from the roadmap"

    all_phases = []
    for version in VERSIONS:
        directory = PLAN / version
        assert (directory / "README.md").exists()
        files = sorted(directory.glob("[0-9][0-9]-*.md"))
        assert len(files) == 5, f"{version}: expected five phase documents"
        all_phases.extend(files)
    assert len(all_phases) == 55

    version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    package = (REPO / "src/yoyackbot/__init__.py").read_text(encoding="utf-8")
    assert version == project["project"]["version"] == "1.0.0.1"
    assert f'__version__ = "{version}"' in package

    matrix = (PLAN / "TEST_MATRIX.md").read_text()
    checks = re.findall(r"^\| `(T\d+-P\d-[AB])` \|", matrix, re.MULTILINE)
    assert len(checks) == len(set(checks)) == 110
    requirements = (PLAN / "REQUIREMENTS.md").read_text()
    assert len(re.findall(r"^\| R\d{2} \|", requirements, re.MULTILINE)) == 39
    assert "§53" in requirements and "§54" in requirements

    status = (PLAN / "STATUS.md").read_text()
    rows = [line for line in status.splitlines() if re.match(r"^\| (?:0\.\d\.0|1\.0\.0)-P[1-5] \|", line)]
    assert len(rows) == 55
    completed = sum("| DONE |" in row for row in rows)
    assert f"개발 완료 **{completed} / 55**" in status

    for document in [REPO / "README.md", *PLAN.rglob("*.md")]:
        text = document.read_text()
        assert text.count("```") % 2 == 0, f"unclosed fence: {document}"
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if link.startswith(("https://", "http://", "mailto:", "#")):
                continue
            target = (document.parent / link.split("#", 1)[0]).resolve()
            assert target.exists(), f"broken link: {document} -> {link}"

    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=REPO
    ).decode().strip("\0").split("\0")
    assert not any(path.startswith(".private/") for path in tracked)
    assert not any(path.startswith(("runtime/", "data/", "tmp/", "logs/")) for path in tracked)
    print(
        f"Plan/source check passed: {len(VERSIONS)} versions, {len(all_phases)} phases, "
        f"{len(checks)} checks, {completed} completed"
    )


if __name__ == "__main__":
    main()
