"""Request-local, safe display labels for stable Discord speaker IDs."""

import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Sequence

from yoyackbot.domain import MessageRecord

_UNSAFE = str.maketrans({
    "@": "＠", "<": "〈", ">": "〉", "`": "′", "*": "＊", "_": "＿",
    "~": "～", "|": "｜", "[": "［", "]": "］", "(": "（", ")": "）",
    "#": "＃", "\\": "＼",
})
_INTERNAL_LABEL = re.compile(r"P[1-9][0-9]*", re.IGNORECASE)
MAX_NAME_LENGTH = 32


def safe_display_name(raw: str) -> str | None:
    """Return a one-line visible label, or None when no reliable name survives."""
    normalized = unicodedata.normalize("NFC", raw)
    printable = "".join(
        character for character in normalized
        if character.isprintable() or character.isspace()
    )
    name = " ".join(printable.split()).strip()
    if not name or name.casefold() == "unknown" or _INTERNAL_LABEL.fullmatch(name):
        return None
    return name.translate(_UNSAFE)[:MAX_NAME_LENGTH].strip() or None


def speaker_labels(messages: Sequence[MessageRecord]) -> dict[int, str]:
    """Prefer each author's latest valid in-range name and number collisions by first turn."""
    ordered = sorted(messages, key=lambda item: (item.created_at, item.message_id))
    latest: dict[int, str] = {}
    authors = dict.fromkeys(item.author_id for item in ordered)
    for item in ordered:
        candidate = safe_display_name(item.author_name)
        if candidate is not None:
            latest[item.author_id] = candidate
    bases = {author_id: latest.get(author_id, "사용자") for author_id in authors}
    duplicate_counts = Counter(bases.values())
    ordinals: dict[str, int] = defaultdict(int)
    labels = {}
    for author_id, base in bases.items():
        if duplicate_counts[base] > 1:
            ordinals[base] += 1
            labels[author_id] = f"{base} ({ordinals[base]})"
        else:
            labels[author_id] = base
    return labels
