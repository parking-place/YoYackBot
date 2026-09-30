"""Keep the human-reviewed quality set executable and attribution-aware."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import serialize_conversation
from yoyackbot.summary_prompt import PROMPT_VERSION, SUMMARY_PROMPT

FIXTURES = Path(__file__).parent / "fixtures" / "summary_quality.json"


def test_twenty_synthetic_cases_have_reviewable_truth_and_speaker_boundaries() -> None:
    cases = json.loads(FIXTURES.read_text())
    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)
    tags = {tag for case in cases for tag in case["tags"]}
    assert {"agreement", "opposition", "question", "answer", "joke", "correction",
            "duplicate_name", "nickname_change", "injection", "unresolved"} <= tags
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    for case in cases:
        assert case["required"] and case["forbidden"] and len(case["messages"]) >= 2
        people = {row[0]: index for index, row in enumerate(case["messages"], start=1)}
        records = [
            MessageRecord(
                index, 1, 10, people[row[0]], row[1], row[2],
                now + timedelta(minutes=index), has_attachment=bool(row[3]) if len(row) > 3 else False,
            )
            for index, row in enumerate(case["messages"], start=1)
        ]
        document = serialize_conversation(
            records, channel_name="합성 시험", range_label="최근 대화",
            trigger_message_id=None, max_bytes=100000,
        )
        rows = [json.loads(line) for line in document.splitlines()]
        assert len(rows) == len(case["messages"]) + 1
        by_person: dict[str, set[str]] = {}
        for raw, serialized in zip(case["messages"], rows[1:], strict=True):
            by_person.setdefault(raw[0], set()).add(serialized["speaker"])
            assert serialized["display_name"] == rows[0]["speaker_names"][serialized["speaker"]]
        assert all(len(speakers) == 1 for speakers in by_person.values())
        assert len({next(iter(speakers)) for speakers in by_person.values()}) == len(by_person)


def test_trusted_prompt_has_explicit_version_and_excludes_fixture_text() -> None:
    assert PROMPT_VERSION == "1.1.0-p2-v1"
    assert "/work/conversation.jsonl" in SUMMARY_PROMPT
    assert "YOYACK_INPUT_UNAVAILABLE" in SUMMARY_PROMPT
    assert "간접 인용" in SUMMARY_PROMPT and "명시적으로" in SUMMARY_PROMPT
    cases = json.loads(FIXTURES.read_text())
    assert all(row[2] not in SUMMARY_PROMPT for case in cases for row in case["messages"])
