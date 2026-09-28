"""Range labels, lossless splits, Markdown continuity, and mention safety."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryResult
from yoyackbot.summary_format import (
    format_summary,
    range_header,
    sanitize_mentions,
    split_body,
    utf16_length,
)

KST = ZoneInfo("Asia/Seoul")
ACCEPTED = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def record(message_id: int, created_at: datetime) -> MessageRecord:
    return MessageRecord(message_id, 1, 1, 1, "가람", "합성 대화", created_at)


def request(start: datetime) -> RangeRequest:
    return RangeRequest(RequestKind.TIME, ACCEPTED, start=start)


def test_kst_headers_use_actual_start_and_accepted_end() -> None:
    assert range_header(request(ACCEPTED - timedelta(hours=1)), [], KST) == (
        "오후 8시 00분부터 지금까지의 요약이오."
    )
    today_midnight = datetime(2026, 9, 28, 0, 0, tzinfo=KST)
    assert range_header(request(today_midnight), [], KST).startswith("오늘 00시 00분부터")
    assert range_header(request(ACCEPTED - timedelta(days=2)), [], KST).startswith(
        "9월 26일 오후 9시 00분부터"
    )
    delayed = range_header(request(ACCEPTED - timedelta(hours=1)), [], KST,
                           posted_at=ACCEPTED + timedelta(seconds=90))
    assert delayed.endswith("(기준: 오후 9시 00분 KST)")


def test_count_header_uses_oldest_selected_message_and_empty_is_rejected() -> None:
    selected = [record(2, ACCEPTED - timedelta(minutes=1)),
                record(1, ACCEPTED - timedelta(hours=2))]
    count = RangeRequest(RequestKind.COUNT, ACCEPTED, count=2)
    assert range_header(count, selected, KST).startswith("오후 7시 00분부터")
    with pytest.raises(ValueError, match="selected messages"):
        range_header(count, [], KST)


@pytest.mark.parametrize("text", [
    "짧은 문장입니다. " * 60,
    "문단 하나입니다.\n\n문단 둘입니다.\n\n" * 20,
    "😀한글" * 90,
    "긴단어" * 180,
    "```python\nprint('안녕')\n" + "x" * 300 + "\n```",
])
def test_split_body_preserves_every_character_and_budget(text: str) -> None:
    pieces = split_body(text, 90)
    assert len(pieces) > 1
    assert "".join(pieces) == text
    assert all(utf16_length(part) <= 90 for part in pieces)


def test_format_summary_first_header_only_and_balanced_fences() -> None:
    body = "```python\n" + "print('안녕')\n" * 35 + "```\n마무리하였소."
    result = SummaryResult(body, "gpt-6-luna", 1)
    chunks = format_summary(request(ACCEPTED - timedelta(hours=1)),
                            [record(1, ACCEPTED - timedelta(minutes=1))], result, KST,
                            limit=140)
    assert len(chunks) > 1
    assert all(utf16_length(chunk) <= 140 for chunk in chunks)
    assert chunks[0].startswith("오후 8시 00분부터 지금까지의 요약이오.")
    assert all("부터 지금까지의 요약이오" not in chunk for chunk in chunks[1:])
    assert all(chunk.count("```") % 2 == 0 for chunk in chunks)
    assert all(f"({index}/{len(chunks)})" in chunk for index, chunk in enumerate(chunks, 1))


def test_mention_sanitization_and_too_short_limit() -> None:
    result = sanitize_mentions("<@123> <@!234> <@&345> <#456> @everyone @here")
    assert result == "@사용자 @사용자 @역할 #채널 ＠everyone ＠here"
    with pytest.raises(ValueError, match="no room"):
        format_summary(request(ACCEPTED - timedelta(hours=1)),
                       [record(1, ACCEPTED)], SummaryResult("내용", "test", 1), KST,
                       limit=10)
