"""Fail CI on secret-shaped data or private paths anywhere in reachable Git history."""

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRIVATE_PATH = re.compile(
    rb"(?:^|/)(?:\.private|auth\.json|runtime|data|logs|tmp)(?:/|$)|"
    rb"(?:\.db(?:-wal|-shm)?|\.pem|\.key)$"
)
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED )?PRIVATE KEY-----"),
    "openai_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(rb"\b(?:gh[puosr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "discord_token": re.compile(rb"\b[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{5,10}\.[A-Za-z0-9_-]{20,}\b"),
}


def scan_object(data: bytes) -> set[str]:
    return {name for name, pattern in SECRET_PATTERNS.items() if pattern.search(data)}


def scan_history(*, live_secrets: tuple[bytes, ...] = ()) -> tuple[int, set[str]]:
    objects = subprocess.check_output(
        ["git", "rev-list", "--objects", "--all"], cwd=REPO
    ).splitlines()
    hashes: set[bytes] = set()
    issues: set[str] = set()
    for line in objects:
        sha, _, path = line.partition(b" ")
        hashes.add(sha)
        if path and PRIVATE_PATH.search(path):
            issues.add("private_path")
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"], cwd=REPO,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        for sha in hashes:
            process.stdin.write(sha + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or int(header[2]) > 16_000_000:
                issues.add("unscanned_object")
                break
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            issues.update(scan_object(data))
            if any(secret and secret in data for secret in live_secrets):
                issues.add("live_secret")
    finally:
        process.stdin.close()
        process.stdout.close()
        process.terminate()
        process.wait(timeout=5)
    return len(hashes), issues


def main() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").encode()
    count, issues = scan_history(live_secrets=(token,) if len(token) >= 20 else ())
    print(f"Public history scan: {count} objects, {len(issues)} issue categories")
    for category in sorted(issues):
        print(f"issue={category}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
