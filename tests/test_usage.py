"""Usage reads pick explicit windows, never guess numbers, and always reap the app-server."""

import asyncio
import os
import sys
import textwrap
from pathlib import Path

import pytest

from yoyackbot.usage import (
    UsageSnapshot,
    UsageUnavailable,
    parse_rate_limits,
    read_account_usage,
    read_usage,
    remaining_percent,
)


def window(used: object, minutes: object) -> dict[str, object]:
    return {"usedPercent": used, "windowDurationMins": minutes, "resetsAt": 1_800_000_000}


def bucket(primary: object, secondary: object, limit_id: object = "codex") -> dict[str, object]:
    return {"limitId": limit_id, "primary": primary, "secondary": secondary}


def single(primary: object, secondary: object) -> dict[str, object]:
    return {"rateLimits": bucket(primary, secondary)}


def test_single_bucket_maps_both_windows() -> None:
    snapshot = parse_rate_limits(single(window(26, 300), window(18, 10080)))
    assert snapshot == UsageSnapshot(74, 82)
    assert not snapshot.warning


def test_windows_are_identified_by_duration_not_order() -> None:
    snapshot = parse_rate_limits(single(window(91, 10080), window(26, 300)))
    assert snapshot == UsageSnapshot(74, 9)
    assert snapshot.warning


def test_multi_bucket_uses_only_the_explicit_codex_bucket() -> None:
    result = {
        "rateLimits": bucket(window(99, 300), window(99, 10080), limit_id="other"),
        "rateLimitsByLimitId": {
            "other": bucket(window(99, 300), window(99, 10080), limit_id="other"),
            "codex": bucket(window(0, 300), window(90, 10080)),
        },
    }
    snapshot = parse_rate_limits(result)
    assert snapshot == UsageSnapshot(100, 10)
    assert snapshot.warning


@pytest.mark.parametrize(
    "result",
    [
        {"rateLimits": bucket(window(1, 300), window(1, 10080), limit_id=None)},
        {"rateLimits": bucket(window(1, 300), window(1, 10080), limit_id="other")},
        {"rateLimitsByLimitId": {"other": bucket(window(1, 300), window(1, 10080))}},
        {"rateLimits": {}, "rateLimitsByLimitId": []},
        [],
        None,
    ],
)
def test_bucket_must_explicitly_match(result: object) -> None:
    with pytest.raises(UsageUnavailable):
        parse_rate_limits(result)


@pytest.mark.parametrize(
    ("used", "remaining", "warning"),
    [(0, 100, False), (89, 11, False), (90, 10, True), (100, 0, True),
     (89.5, 10, True), (10.4, 89, False), (0.1, 99, False)],
)
def test_boundaries_and_conservative_rounding(used: float, remaining: int, warning: bool) -> None:
    assert remaining_percent(used) == remaining
    snapshot = parse_rate_limits(single(window(used, 300), window(0, 10080)))
    assert snapshot.five_hour_remaining == remaining
    assert snapshot.warning is warning


@pytest.mark.parametrize(
    "used", [None, "26", True, -1, 100.1, float("nan"), float("inf")]
)
def test_invalid_used_percent_is_unavailable(used: object) -> None:
    with pytest.raises(UsageUnavailable):
        parse_rate_limits(single(window(used, 300), window(0, 10080)))


@pytest.mark.parametrize(
    ("primary", "secondary", "expected"),
    [
        (window(1, 10080), None, UsageSnapshot(None, 99)),
        (None, window(95, 300), UsageSnapshot(5, None)),
        (window(90, 10080), None, UsageSnapshot(None, 10)),
    ],
)
def test_a_single_reported_window_is_shown_alone(
    primary: object, secondary: object, expected: UsageSnapshot,
) -> None:
    snapshot = parse_rate_limits(single(primary, secondary))
    assert snapshot == expected
    assert snapshot.warning is (min(v for v in (expected.five_hour_remaining,
                                                   expected.weekly_remaining) if v is not None) <= 10)


@pytest.mark.parametrize(
    ("primary", "secondary"),
    [
        (None, None),
        (window(1, 300), window(1, 300)),
        (window(1, 300), window(1, 1440)),
        (window(1, None), window(1, 10080)),
        (window(1, True), window(1, 10080)),
        (window(1, 300), "bad"),
    ],
)
def test_missing_or_unexpected_windows_are_unavailable(primary: object, secondary: object) -> None:
    with pytest.raises(UsageUnavailable):
        parse_rate_limits(single(primary, secondary))


FAKE_SERVER = textwrap.dedent(
    """
    import json, os, sys, time
    mode = sys.argv[1]
    log = open(sys.argv[2], "a")
    log.write(f"pid {os.getpid()}\\n"); log.flush()
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()
    result = {"rateLimits": {"limitId": "codex",
        "primary": {"usedPercent": 26, "windowDurationMins": 300},
        "secondary": {"usedPercent": 18, "windowDurationMins": 10080}}}
    for line in sys.stdin:
        message = json.loads(line)
        log.write(message.get("method", "?") + "\\n"); log.flush()
        if message.get("method") == "initialize":
            if mode == "hang":
                time.sleep(60)
            send({"method": "remoteControl/status/changed", "params": {}})
            send({"id": message["id"], "result": {"userAgent": "synthetic"}})
        elif message.get("method") == "account/rateLimits/read":
            if mode == "error":
                send({"id": message["id"], "error": {"code": -1, "message": "token secret"}})
            elif mode == "flood":
                send({"method": "noise", "params": {"x": "y" * 4096}})
                send({"method": "noise", "params": {"x": "y" * 4096}})
            elif mode == "garbage":
                sys.stdout.write("not json\\n"); sys.stdout.flush()
            elif mode == "close":
                sys.exit(0)
            else:
                send({"method": "account/rateLimits/updated", "params": {
                    "rateLimits": {"limitId": "codex",
                        "primary": {"usedPercent": 99, "windowDurationMins": 300},
                        "secondary": {"usedPercent": 99, "windowDurationMins": 10080}}}})
                send({"id": message["id"] + 100, "result": {}})
                send({"id": message["id"], "result": result})
    """
)


def run_fake(tmp_path: Path, mode: str, **kwargs: object) -> tuple[UsageSnapshot, list[str]]:
    script = tmp_path / "server.py"
    script.write_text(FAKE_SERVER)
    log = tmp_path / "log"
    command = [sys.executable, str(script), mode, str(log)]
    try:
        snapshot = asyncio.run(read_usage(command, env={"PATH": os.environ["PATH"]}, **kwargs))
    finally:
        lines = log.read_text().splitlines() if log.exists() else []
    return snapshot, lines


def assert_reaped(lines: list[str]) -> None:
    pid = int(lines[0].split()[1])
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_protocol_skips_notifications_and_foreign_ids(tmp_path: Path) -> None:
    snapshot, lines = run_fake(tmp_path, "ok")
    assert snapshot == UsageSnapshot(74, 82)
    assert lines[1:] == ["initialize", "initialized", "account/rateLimits/read"]
    assert_reaped(lines)


@pytest.mark.parametrize("mode", ["error", "garbage", "close"])
def test_protocol_failures_hide_raw_diagnostics(tmp_path: Path, mode: str) -> None:
    with pytest.raises(UsageUnavailable) as caught:
        run_fake(tmp_path, mode)
    assert "secret" not in str(caught.value)
    assert_reaped((tmp_path / "log").read_text().splitlines())


def test_timeout_kills_the_child(tmp_path: Path) -> None:
    with pytest.raises(UsageUnavailable, match="timed out"):
        run_fake(tmp_path, "hang", timeout=0.5)
    assert_reaped((tmp_path / "log").read_text().splitlines())


def test_output_limit_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(UsageUnavailable, match="output limit|too long"):
        run_fake(tmp_path, "flood", max_output=6000)
    assert_reaped((tmp_path / "log").read_text().splitlines())


def test_missing_executable_is_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(UsageUnavailable):
        asyncio.run(read_usage([str(tmp_path / "missing")], env={}))


ACCOUNT_SERVER = textwrap.dedent(
    """
    import json, os, sys
    assert sys.argv[1] == "app-server"
    home = os.environ["CODEX_HOME"]
    with open(os.path.join(home, "seen"), "w") as seen:
        seen.write(home)
    open(os.path.join(home, "state_5.sqlite"), "w").close()
    if REFRESH:
        with open(os.path.join(home, "auth.json"), "w") as auth:
            json.dump({"tokens": {"access_token": "new-a", "refresh_token": "new-r"}}, auth)
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        message = json.loads(line)
        if message.get("method") == "initialize":
            send({"id": message["id"], "result": {}})
        elif message.get("method") == "account/rateLimits/read":
            send({"id": message["id"], "result": {"rateLimits": {"limitId": "codex",
                "primary": {"usedPercent": 26, "windowDurationMins": 300},
                "secondary": {"usedPercent": 18, "windowDurationMins": 10080}}}})
    """
)
ORIGINAL_AUTH = b'{"tokens": {"access_token": "old-a", "refresh_token": "old-r"}}'


def account_fixture(tmp_path: Path, *, refresh: bool) -> tuple[Path, Path, Path]:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        f"#!{sys.executable}\nREFRESH = {refresh}\n" + ACCOUNT_SERVER
    )
    executable.chmod(0o700)
    auth_dir = tmp_path / "model-auth"
    auth_dir.mkdir(mode=0o700)
    auth = auth_dir / "auth.json"
    auth.write_bytes(ORIGINAL_AUTH)
    auth.chmod(0o600)
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    return executable, auth, work


def test_account_usage_uses_a_disposable_home(tmp_path: Path) -> None:
    executable, auth, work = account_fixture(tmp_path, refresh=False)
    snapshot = asyncio.run(read_account_usage(str(executable), auth, work))
    assert snapshot == UsageSnapshot(74, 82)
    assert auth.read_bytes() == ORIGINAL_AUTH
    assert sorted(path.name for path in auth.parent.iterdir()) == ["auth.json"]
    assert list(work.iterdir()) == []


def test_account_usage_keeps_a_valid_refresh(tmp_path: Path) -> None:
    executable, auth, work = account_fixture(tmp_path, refresh=True)
    asyncio.run(read_account_usage(str(executable), auth, work))
    assert b"new-r" in auth.read_bytes()
    assert (auth.stat().st_mode & 0o777) == 0o600
    assert list(work.iterdir()) == []


def test_account_usage_rejects_shared_auth(tmp_path: Path) -> None:
    executable, auth, work = account_fixture(tmp_path, refresh=False)
    auth.chmod(0o644)
    with pytest.raises(UsageUnavailable):
        asyncio.run(read_account_usage(str(executable), auth, work))
    with pytest.raises(UsageUnavailable):
        asyncio.run(read_account_usage("fake-codex", auth, work))
    assert list(work.iterdir()) == []
