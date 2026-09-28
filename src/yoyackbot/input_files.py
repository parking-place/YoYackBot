"""Bounded, request-private conversation documents for the Codex summarizer."""

import json
import os
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Self

from yoyackbot.domain import MessageRecord

MENTION = re.compile(r"<@(?P<role>&)?(?P<member>!)?(?P<user>\d+)>|<#(?P<channel>\d+)>")


class InputFileError(RuntimeError):
    """Input material could not be prepared safely; details never include message text."""


def _name(raw: str) -> str:
    """Keep a display label on one line without changing the message body."""
    return "".join(char for char in raw if char.isprintable() and char not in "\r\n")[:80] or "사용자"


def _mentions(content: str, names: dict[int, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group("channel") is not None:
            return "#채널"
        if match.group("role") is not None:
            return "@역할"
        return "@" + names.get(int(match.group("user")), "사용자")

    return MENTION.sub(replace, content)


def serialize_conversation(
    messages: Sequence[MessageRecord],
    *,
    channel_name: str,
    range_label: str,
    trigger_message_id: int | None,
    max_bytes: int,
) -> bytes:
    """Use JSON lines so quoted names and multiline bodies cannot forge record boundaries."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    ordered = sorted(
        (item for item in messages if item.message_id != trigger_message_id),
        key=lambda item: (item.created_at, item.message_id),
    )
    names = {item.author_id: _name(item.author_name) for item in ordered}
    speakers = {author_id: f"P{index}" for index, author_id in enumerate(names, start=1)}
    lines = [json.dumps({"type": "scope", "channel": _name(channel_name),
                         "range": _name(range_label)}, ensure_ascii=False)]
    for item in ordered:
        lines.append(json.dumps({
            "type": "message",
            "time": item.created_at.astimezone(UTC).isoformat(),
            "speaker": speakers[item.author_id],
            "display_name": _name(item.author_name),
            "body": _mentions(item.content, names),
            "reply": item.is_reply,
            "attachment_present": item.has_attachment,
        }, ensure_ascii=False))
    data = ("\n".join(lines) + "\n").encode("utf-8")
    if len(data) > max_bytes:
        raise InputFileError("Conversation input exceeds configured size")
    return data


def _private_root(root: Path) -> None:
    if not root.is_absolute() or ".." in root.parts:
        raise InputFileError("Input directory must be an absolute path without traversal")
    try:
        if any(part.is_symlink() for part in (root, *root.parents)):
            raise InputFileError("Input directory cannot pass through a symlink")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
    except OSError as exc:
        raise InputFileError("Input directory unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise InputFileError("Input directory must be private and owned by the bot")


@dataclass
class InputWorkspace:
    directory: Path
    log_file: Path
    output_directory: Path

    @classmethod
    def create(cls, root: Path, data: bytes) -> "InputWorkspace":
        _private_root(root)
        try:
            directory = Path(tempfile.mkdtemp(prefix="request-", dir=root))
            output_directory = directory / "output"
            output_directory.mkdir(mode=0o700)
            fd, name = tempfile.mkstemp(prefix="conversation-", suffix=".jsonl", dir=directory)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
            return cls(directory, Path(name), output_directory)
        except BaseException as exc:
            if "directory" in locals():
                shutil.rmtree(directory)
            raise InputFileError("Unable to write private conversation input") from exc

    def close(self) -> None:
        try:
            shutil.rmtree(self.directory)
        except FileNotFoundError:
            pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def cleanup_stale_workspaces(
    root: Path, *, older_than_seconds: int, active: frozenset[Path] = frozenset(),
    now: float | None = None,
) -> int:
    """Remove only this service's old direct children, leaving active work untouched."""
    if older_than_seconds < 1:
        raise ValueError("older_than_seconds must be positive")
    _private_root(root)
    cutoff = (time.time() if now is None else now) - older_than_seconds
    removed = 0
    try:
        for child in root.iterdir():
            if not child.name.startswith("request-") or child in active:
                continue
            info = child.lstat()
            if (
                stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.geteuid()
                and not info.st_mode & 0o077
                and info.st_mtime <= cutoff
            ):
                shutil.rmtree(child)
                removed += 1
    except OSError as exc:
        raise InputFileError("Stale request cleanup failed") from exc
    return removed
