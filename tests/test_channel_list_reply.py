"""Exact channel list wording, escaping, splitting, and help (T102b-P2)."""

import pytest

from yoyackbot.channel_list import (
    EMPTY_NOTICE,
    LIST_FOOTER,
    LIST_HEADER,
    channel_list_messages,
    escape_name,
)
from yoyackbot.parser import HELP_TEXT, help_text


def test_user_example_matches_character_for_character() -> None:
    assert channel_list_messages(["ㄴㄴㄴ", "ㅇㅇㅇ", "ㅎㅎㅎ"]) == [
        "📡👀 지금 본인이 보고 있는 채널을 알려주겠소\n - 💬 ㄴㄴㄴ\n - 💬 ㅇㅇㅇ\n - 💬 ㅎㅎㅎ\n✅ 이상이오. 🫡"
    ]


def test_single_channel() -> None:
    assert channel_list_messages(["잡담"]) == [f"{LIST_HEADER}\n - 💬 잡담\n{LIST_FOOTER}"]


def test_no_visible_channel_uses_the_empty_notice() -> None:
    assert channel_list_messages([]) == [EMPTY_NOTICE]
    assert EMPTY_NOTICE == "🫥 지금 보고 있는 채널이 없소. `/채널 설정`으로 정하시오. 🛠️"


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("봇-명령어", "봇-명령어"),
        ("a*b", "a\\*b"),
        ("under_score", "under\\_score"),
        ("tick`s", "tick\\`s"),
        ("@everyone", "@everyone"),
        ("||spoiler||", "\\|\\|spoiler\\|\\|"),
        ("> quote", "\\> quote"),
    ],
)
def test_names_are_shown_literally(name: str, shown: str) -> None:
    assert escape_name(name) == shown
    assert channel_list_messages([name])[0].splitlines()[1] == f" - 💬 {shown}"


def test_long_lists_split_between_whole_lines_in_order() -> None:
    names = [f"채널{index:03d}-" + "가" * 60 for index in range(80)]
    parts = channel_list_messages(names, limit=500)
    assert len(parts) > 1
    assert all(len(part) <= 500 for part in parts)
    assert parts[0].startswith(LIST_HEADER + "\n")
    assert parts[-1].endswith("\n" + LIST_FOOTER)
    assert sum(part.count(LIST_HEADER) for part in parts) == 1
    assert sum(part.count(LIST_FOOTER) for part in parts) == 1
    lines = "\n".join(parts).splitlines()
    assert lines == [LIST_HEADER, *(f" - 💬 {name}" for name in names), LIST_FOOTER]


def test_default_limit_keeps_small_lists_in_one_message() -> None:
    assert len(channel_list_messages([f"채널{index}" for index in range(25)])) == 1


def test_help_mentions_the_channel_command() -> None:
    assert "📡 `채널` → 주시 채널" in HELP_TEXT
    assert len(HELP_TEXT) < 2000 and len(help_text()) < 2000