"""Every user-facing notice line opens with an emoji, and the wording stays haoche (T113a)."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from yoyackbot.channel_list import EMPTY_NOTICE as CHANNEL_EMPTY_NOTICE
from yoyackbot.channel_list import LIST_FOOTER, LIST_HEADER, channel_list_messages
from yoyackbot.status_report import StatusReport, status_message
from yoyackbot.usage import (
    USAGE_EXHAUSTED_NOTICE,
    USAGE_UNAVAILABLE_NOTICE,
    UsageSnapshot,
    usage_message,
)

EMOJI = re.compile(r"^(?:\s*-\s+)?[\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿]")
HAOCHE = re.compile(r"(?:소|오|요|시오|구려|겠소|었소|았소|하오|이오)[.!?…]*(?:\.\.\.)?$")
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
# Released wordings that end differently on purpose (a header without ending, a blessing).
KEPT_ENDINGS = ("알려주겠소", "함께하길...")


def lines_of(*texts: str) -> list[str]:
    return [line for text in texts for line in text.splitlines() if line.strip()]


def strip_trailing_emoji(line: str) -> str:
    return re.sub(r"[\s\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿️‍]+$", "", line)


def command_reply_texts() -> list[str]:
    report = StatusReport(gateway_ready=True, watched_channels=2, cached_messages=3, database_bytes=1_000_000,
                          model="gpt-6-luna / low", last_success=NOW - timedelta(minutes=3),
                          last_success_known=True)
    broken = StatusReport(gateway_ready=False, watched_channels=None, cached_messages=None, database_bytes=None,
                          model=None, last_success=None, last_success_known=False)
    return [
        usage_message(UsageSnapshot(74, 82)), usage_message(UsageSnapshot(None, 6)),
        USAGE_UNAVAILABLE_NOTICE, USAGE_EXHAUSTED_NOTICE,
        status_message(report, NOW), status_message(broken, NOW),
        *channel_list_messages(["잡담", "개발"]), CHANNEL_EMPTY_NOTICE, LIST_HEADER, LIST_FOOTER,
    ]


@pytest.mark.parametrize("line", lines_of(*command_reply_texts()))
def test_command_reply_lines_open_with_emoji(line: str) -> None:
    assert EMOJI.match(line), line


@pytest.mark.parametrize(
    "line", [line for line in lines_of(*command_reply_texts())
             if not line.lstrip().startswith("-") and ":" not in line
             and not any(kept in line for kept in KEPT_ENDINGS)],
)
def test_command_reply_sentences_keep_haoche(line: str) -> None:
    assert HAOCHE.search(strip_trailing_emoji(line)), line
