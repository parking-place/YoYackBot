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
    assert version == project["project"]["version"] == "1.4.1"
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

    minor = PLAN / "1.1.0"
    assert len(sorted(minor.glob("0[1-5]-*.md"))) == 5, "1.1.0: expected five phase documents"
    minor_checks = re.findall(
        r"^\| `(T110-P[1-5]-[AB])` \|", (minor / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(minor_checks) == len(set(minor_checks)) == 10
    minor_rows = [
        line for line in (minor / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.0-P[1-5]\]", line)
    ]
    assert len(minor_rows) == 5
    minor_done = sum("| DONE |" in row for row in minor_rows)

    readable = PLAN / "1.1.0a"
    assert len(sorted(readable.glob("0[1-4]-*.md"))) == 4, "1.1.0a: expected four phase documents"
    readable_checks = re.findall(
        r"^\| `(T110a-P[1-4]-[AB])` \|", (readable / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(readable_checks) == len(set(readable_checks)) == 8
    readable_rows = [
        line for line in (readable / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.0a-P[1-4]\]", line)
    ]
    assert len(readable_rows) == 4
    readable_done = sum("| DONE |" in row for row in readable_rows)

    priority = PLAN / "1.1.1"
    assert len(sorted(priority.glob("0[1-4]-*.md"))) == 4, "1.1.1: expected four phase documents"
    priority_checks = re.findall(
        r"^\| `(T111-P[1-4]-[AB])` \|", (priority / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(priority_checks) == len(set(priority_checks)) == 8
    priority_rows = [
        line for line in (priority / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.1-P[1-4]\]", line)
    ]
    assert len(priority_rows) == 4
    priority_done = sum("| DONE |" in row for row in priority_rows)

    ongoing = PLAN / "1.1.1a"
    assert len(sorted(ongoing.glob("0[1-4]-*.md"))) == 4, "1.1.1a: expected four phase documents"
    ongoing_checks = re.findall(
        r"^\| `(T111a-P[1-4]-[AB])` \|", (ongoing / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(ongoing_checks) == len(set(ongoing_checks)) == 8
    ongoing_rows = [
        line for line in (ongoing / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.1a-P[1-4]\]", line)
    ]
    assert len(ongoing_rows) == 4
    ongoing_done = sum("| DONE |" in row for row in ongoing_rows)

    lively = PLAN / "1.1.2"
    assert len(sorted(lively.glob("0[1-4]-*.md"))) == 4, "1.1.2: expected four phase documents"
    lively_checks = re.findall(
        r"^\| `(T112-P[1-4]-[AB])` \|", (lively / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(lively_checks) == len(set(lively_checks)) == 8
    lively_rows = [
        line for line in (lively / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.2-P[1-4]\]", line)
    ]
    assert len(lively_rows) == 4
    lively_done = sum("| DONE |" in row for row in lively_rows)

    markdown = PLAN / "1.1.2a"
    assert len(sorted(markdown.glob("0[1-5]-*.md"))) == 5, "1.1.2a: expected five phase documents"
    markdown_checks = re.findall(
        r"^\| `(T112a-P[1-5]-[AB])` \|", (markdown / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(markdown_checks) == len(set(markdown_checks)) == 10
    markdown_rows = [
        line for line in (markdown / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.2a-P[1-5]\]", line)
    ]
    assert len(markdown_rows) == 5
    markdown_done = sum("| DONE |" in row for row in markdown_rows)

    managers = PLAN / "1.1.3"
    assert len(sorted(managers.glob("0[1-3]-*.md"))) == 3, "1.1.3: expected three phase documents"
    manager_checks = re.findall(
        r"^\| `(T113-P[1-3]-[AB])` \|", (managers / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(manager_checks) == len(set(manager_checks)) == 6
    manager_rows = [
        line for line in (managers / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.3-P[1-3]\]", line)
    ]
    assert len(manager_rows) == 3
    manager_done = sum("| DONE |" in row for row in manager_rows)

    notices = PLAN / "1.1.3a"
    assert len(sorted(notices.glob("0[1-3]-*.md"))) == 3, "1.1.3a: expected three phase documents"
    notice_emoji_checks = re.findall(
        r"^\| `(T113a-P[1-3]-[AB])` \|", (notices / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(notice_emoji_checks) == len(set(notice_emoji_checks)) == 6
    notice_emoji_rows = [
        line for line in (notices / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.1\.3a-P[1-3]\]", line)
    ]
    assert len(notice_emoji_rows) == 3
    notice_emoji_done = sum("| DONE |" in row for row in notice_emoji_rows)

    def seven_phase(name: str, prefix: str, letters: str, total: int) -> tuple[int, int]:
        """1.2.0 and the planned 1.3.0: seven phases and their matrix checks."""
        directory = PLAN / name
        assert len(sorted(directory.glob("0[1-7]-*.md"))) == 7, f"{name}: expected seven phases"
        found = re.findall(
            rf"^\| `({prefix}-P[1-7]-[{letters}])` \|", (directory / "TEST_MATRIX.md").read_text(),
            re.MULTILINE,
        )
        assert len(found) == len(set(found)) == total, f"{name}: expected {total} checks"
        rows = [
            line for line in (directory / "STATUS.md").read_text().splitlines()
            if re.match(rf"^\| \[{re.escape(name)}-P[1-7]\]", line)
        ]
        assert len(rows) == 7
        return sum("| DONE |" in row for row in rows), len(found)

    fixes_done, fixes_checks = seven_phase("1.2.0", "T120", "A-D", 28)
    tone_next_done, tone_next_checks = seven_phase("1.3.0", "T130", "A-C", 16)

    tidy = PLAN / "1.3.1"
    assert len(sorted(tidy.glob("0[1-4]-*.md"))) == 4, "1.3.1: expected four phase documents"
    tidy_checks = re.findall(
        r"^\| `(T131-P[1-4]-[AB])` \|", (tidy / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(tidy_checks) == len(set(tidy_checks)) == 8
    tidy_rows = [
        line for line in (tidy / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.3\.1-P[1-4]\]", line)
    ]
    assert len(tidy_rows) == 4
    tidy_done = sum("| DONE |" in row for row in tidy_rows)

    timed = PLAN / "1.3.2"
    assert len(sorted(timed.glob("0[1-2]-*.md"))) == 2, "1.3.2: expected two phase documents"
    timed_checks = re.findall(
        r"^\| `(T132-P[1-2]-[AB])` \|", (timed / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(timed_checks) == len(set(timed_checks)) == 4
    timed_rows = [
        line for line in (timed / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.3\.2-P[1-2]\]", line)
    ]
    assert len(timed_rows) == 2
    timed_done = sum("| DONE |" in row for row in timed_rows)

    faster = PLAN / "1.3.3"
    assert len(sorted(faster.glob("0[1-6]-*.md"))) == 6, "1.3.3: expected six phase documents"
    faster_checks = re.findall(
        r"^\| `(T133-P[1-6]-[ABC])` \|", (faster / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(faster_checks) == len(set(faster_checks)) == 13
    faster_rows = [
        line for line in (faster / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.3\.3-P[1-6]\]", line)
    ]
    assert len(faster_rows) == 6
    faster_done = sum("| DONE |" in row for row in faster_rows)

    hidden = PLAN / "1.3.4"
    assert len(sorted(hidden.glob("0[1-2]-*.md"))) == 2, "1.3.4: expected two phase documents"
    hidden_checks = re.findall(
        r"^\| `(T134-P[1-2]-[AB])` \|", (hidden / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(hidden_checks) == len(set(hidden_checks)) == 4
    hidden_rows = [
        line for line in (hidden / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.3\.4-P[1-2]\]", line)
    ]
    assert len(hidden_rows) == 2
    hidden_done = sum("| DONE |" in row for row in hidden_rows)

    executed = PLAN / "1.4.0"
    assert len(sorted(executed.glob("0[1-7]-*.md"))) == 7, "1.4.0: expected seven phase documents"
    executed_checks = re.findall(
        r"^\| `(T140-P[1-7]-[ABC])` \|", (executed / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(executed_checks) == len(set(executed_checks)) == 15
    executed_rows = [
        line for line in (executed / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.4\.0-P[1-7]\]", line)
    ]
    assert len(executed_rows) == 7
    executed_done = sum("| DONE |" in row for row in executed_rows)

    pardoned = PLAN / "1.4.1"
    assert len(sorted(pardoned.glob("0[1-2]-*.md"))) == 2, "1.4.1: expected two phase documents"
    pardoned_checks = re.findall(
        r"^\| `(T141-P[1-2]-[AB])` \|", (pardoned / "TEST_MATRIX.md").read_text(), re.MULTILINE
    )
    assert len(pardoned_checks) == len(set(pardoned_checks)) == 4
    pardoned_rows = [
        line for line in (pardoned / "STATUS.md").read_text().splitlines()
        if re.match(r"^\| \[1\.4\.1-P[1-2]\]", line)
    ]
    assert len(pardoned_rows) == 2
    pardoned_done = sum("| DONE |" in row for row in pardoned_rows)

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
        f"1.0.2c {tone_done}/4 phases, {len(tone_checks)} checks; "
        f"1.1.0 {minor_done}/5 phases, {len(minor_checks)} checks; "
        f"1.1.0a {readable_done}/4 phases, {len(readable_checks)} checks; "
        f"1.1.1 {priority_done}/4 phases, {len(priority_checks)} checks; "
        f"1.1.1a {ongoing_done}/4 phases, {len(ongoing_checks)} checks; "
        f"1.1.2 {lively_done}/4 phases, {len(lively_checks)} checks; "
        f"1.1.2a {markdown_done}/5 phases, {len(markdown_checks)} checks; "
        f"1.1.3 {manager_done}/3 phases, {len(manager_checks)} checks; "
        f"1.1.3a {notice_emoji_done}/3 phases, {len(notice_emoji_checks)} checks; "
        f"1.2.0 {fixes_done}/7 phases, {fixes_checks} checks; "
        f"1.3.0 {tone_next_done}/7 phases, {tone_next_checks} checks; "
        f"1.3.1 {tidy_done}/4 phases, {len(tidy_checks)} checks; "
        f"1.3.2 {timed_done}/2 phases, {len(timed_checks)} checks; "
        f"1.3.3 {faster_done}/6 phases, {len(faster_checks)} checks; "
        f"1.3.4 {hidden_done}/2 phases, {len(hidden_checks)} checks; "
        f"1.4.0 {executed_done}/7 phases, {len(executed_checks)} checks; "
        f"1.4.1 {pardoned_done}/2 phases, {len(pardoned_checks)} checks"
    )


if __name__ == "__main__":
    main()
