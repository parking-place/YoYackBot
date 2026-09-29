"""The public nickname contract uses only safe names from selected messages."""

from datetime import UTC, datetime, timedelta

from yoyackbot.domain import MessageRecord
from yoyackbot.speaker_names import MAX_NAME_LENGTH, safe_display_name, speaker_labels

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def row(number: int, author: int, name: str, *, guild: int = 1) -> MessageRecord:
    return MessageRecord(number, guild, 10, author, name, "합성 대화", NOW + timedelta(seconds=number))


def test_latest_valid_name_and_collision_order_are_deterministic() -> None:
    messages = [
        row(1, 10, "옛 이름"), row(2, 20, "나래"), row(3, 30, "나래"),
        row(4, 10, "새 이름"), row(5, 10, " \n "),
    ]
    expected = {10: "새 이름", 20: "나래 (1)", 30: "나래 (2)"}
    assert speaker_labels(messages) == expected
    assert speaker_labels(list(reversed(messages))) == expected


def test_missing_names_and_internal_key_names_never_leak_ids() -> None:
    labels = speaker_labels([
        row(1, 123456789, ""), row(2, 222222222, "unknown"),
        row(3, 333333333, "P1"),
    ])
    assert list(labels.values()) == ["사용자 (1)", "사용자 (2)", "사용자 (3)"]
    assert all(str(author) not in label for author, label in labels.items())


def test_unicode_markdown_mentions_and_length_are_safe() -> None:
    label = safe_display_name("  나래\n@everyone <@123> *x* 👋  ")
    assert label is not None
    assert "나래" in label and "👋" in label
    assert "@everyone" not in label and "<@123>" not in label
    assert all(character not in label for character in "`*_~|[]#\\")
    assert safe_display_name("_[x]#`~|\\") == "＿［x］＃′～｜＼"
    assert len(label) <= MAX_NAME_LENGTH
    assert safe_display_name("가" * 100) == "가" * MAX_NAME_LENGTH
    assert safe_display_name("\u202e\u2066\n") is None


def test_mapping_is_request_local_across_guilds() -> None:
    first = speaker_labels([row(1, 10, "가람", guild=1), row(2, 20, "가람", guild=1)])
    other = speaker_labels([row(3, 10, "나래", guild=2)])
    assert first == {10: "가람 (1)", 20: "가람 (2)"}
    assert other == {10: "나래"}
