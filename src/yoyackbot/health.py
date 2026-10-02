"""Private, bounded gateway heartbeat for operations checks."""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

HEARTBEAT_NAME = "gateway-health.json"
# Worker states that mean collection is progressing or deliberately idle.
COLLECTION_OK = frozenset({"running", "waiting", "disabled"})
COLLECTION_STATES = COLLECTION_OK | {
    "starting", "backoff", "restarting", "stalled", "failed", "stopped",
}


def write_heartbeat(
    root: Path, *, gateway_ready: bool, collection_worker: str = "disabled",
) -> None:
    if collection_worker not in COLLECTION_STATES:
        raise ValueError("Unknown collection worker state")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".health-", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({
                "pid": os.getpid(),
                "updated_at": datetime.now(UTC).isoformat(),
                "gateway_ready": gateway_ready,
                "collection_worker": collection_worker,
            }, stream)
        os.replace(name, root / HEARTBEAT_NAME)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_heartbeat(root: Path, *, max_age_seconds: int = 30) -> tuple[bool, bool]:
    alive, gateway_ready, _worker = read_heartbeat_details(root, max_age_seconds=max_age_seconds)
    return alive, gateway_ready


def read_heartbeat_details(
    root: Path, *, max_age_seconds: int = 30,
) -> tuple[bool, bool, str | None]:
    """Process liveness, Gateway readiness, and the collection worker state (None if unknown)."""
    try:
        path = root / HEARTBEAT_NAME
        if path.is_symlink() or path.stat().st_mode & 0o077:
            return False, False, None
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = data["pid"]
        updated = datetime.fromisoformat(data["updated_at"])
        if type(pid) is not int or pid < 1 or updated.tzinfo is None:
            return False, False, None
        age = (datetime.now(UTC) - updated).total_seconds()
        if age < 0 or age > max_age_seconds:
            return False, False, None
        os.kill(pid, 0)
        worker = data.get("collection_worker")
        return True, data.get("gateway_ready") is True, (
            worker if worker in COLLECTION_STATES else None
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False, False, None
