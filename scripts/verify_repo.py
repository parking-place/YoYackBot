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
    assert version == project["project"]["version"] == "1.0.2.2"
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

    patch = PLAN / "1.0.1"
    patch_phases = sorted(patch.glob("0[1-6]-*.md"))
    assert len(patch_phases) == 6, "1.0.1: expected six phase documents"
    patch_checks = re.findall(
        r"^\| `(T101-P[1-6]-[AB])` \|", (patch / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(patch_checks) == len(set(patch_checks)) == 12
    patch_rows = [
        line for line in (patch / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.0\.1-P[1-6]\]", line)
    ]
    assert len(patch_rows) == 6
    patch_done = sum("| DONE |" in row for row in patch_rows)

    notices = PLAN / "1.0.2"
    assert len(sorted(notices.glob("0[1-5]-*.md"))) == 5, "1.0.2: expected five phase documents"
    notice_checks = re.findall(
        r"^\| `(T102-P[1-5]-[AB])` \|", (notices / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(notice_checks) == len(set(notice_checks)) == 10
    notice_rows = [
        line for line in (notices / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.0\.2-P[1-5]\]", line)
    ]
    assert len(notice_rows) == 5
    notice_done = sum("| DONE |" in row for row in notice_rows)

    listing = PLAN / "1.0.2b"
    assert len(sorted(listing.glob("0[1-3]-*.md"))) == 3, "1.0.2b: expected three phase documents"
    listing_checks = re.findall(
        r"^\| `(T102b-P[1-3]-[AB])` \|", (listing / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(listing_checks) == len(set(listing_checks)) == 6
    listing_rows = [
        line for line in (listing / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.0\.2b-P[1-3]\]", line)
    ]
    assert len(listing_rows) == 3
    listing_done = sum("| DONE |" in row for row in listing_rows)

    tone = PLAN / "1.0.2c"
    assert len(sorted(tone.glob("0[1-4]-*.md"))) == 4, "1.0.2c: expected four phase documents"
    tone_checks = re.findall(
        r"^\| `(T102c-P[1-4]-[AB])` \|", (tone / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(tone_checks) == len(set(tone_checks)) == 8
    tone_rows = [
        line for line in (tone / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.0\.2c-P[1-4]\]", line)
    ]
    assert len(tone_rows) == 4
    tone_done = sum("| DONE |" in row for row in tone_rows)

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
        f"{len(checks)} checks, {completed} completed; 1.0.1 {patch_done}/6 phases, "
        f"{len(patch_checks)} checks; 1.0.2 {notice_done}/5 phases, {len(notice_checks)} checks; "
        f"1.0.2b {listing_done}/3 phases, {len(listing_checks)} checks; "
        f"1.0.2c {tone_done}/4 phases, {len(tone_checks)} checks"
    )


if __name__ == "__main__":
    main()
