"""1.3.0-P1: ten rating candidates, banned angles, and the recent-ratings store (T130-P1-A/B)."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from yoyackbot.domain import MessageRecord
from yoyackbot.message_store import SQLiteMessageStore
from yoyackbot.output_quality import RATING_LABEL
from yoyackbot.rating_pool import (
    RECENT_LIMIT,
    SQLiteRecentRatings,
    banned_angle,
    filter_candidates,
    parse_candidates,
    parse_judgement,
    usable_rating,
)
from yoyackbot.settings_backup import backup_settings
from yoyackbot.summary_prompt import (
    RATING_CANDIDATES_PROMPT,
    RATING_JUDGE_PROMPT,
    SUMMARY_PROMPT,
    rating_candidates_prompt,
)
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def flat(text: str) -> str:
    return " ".join(text.split())


# T130-P1-A ------------------------------------------------------------------------------

def test_candidate_and_summary_prompts_ban_the_overused_angle() -> None:
    for text in (flat(RATING_CANDIDATES_PROMPT), flat(SUMMARY_PROMPT)):
        for word in ("튄다", "왔다갔다", "오락가락", "정신없다", "부산하다", "요란하다", "한 상 가득", "뒤엉켰다"):
            assert word in text, word
        assert "떡밥 주제어는 짚어도 되지만 사람 이름·숫자·시간은" in text
    candidates = flat(RATING_CANDIDATES_PROMPT)
    assert "정확히 10줄" in candidates and "`번호. **요약창섭의 떡밥 한줄 평가** : <평가>`" in candidates
    assert "recent_rating 줄과 같은 소재·같은 틀은 피하시오" in candidates
    assert "결론이 안 났다·미뤘다·제자리다·끝맺음이 없다는 식의 미결·미룸" in candidates
    judge = flat(RATING_JUDGE_PROMPT)
    assert "'주제가 바뀌어 정신없다'" in judge and "비슷함: <번호들을 쉼표로, 없으면 없음>" in judge
    assert "선택: <번호 하나, 모두 비슷하면 없음>" in judge


@pytest.mark.parametrize("note", ["욕 빼고", "이모지 빼고", "시간순으로 해줘"])
def test_request_note_is_quoted_into_the_candidate_prompt(note) -> None:
    prompt = rating_candidates_prompt(note)
    assert prompt.startswith(RATING_CANDIDATES_PROMPT) and f"«{note}»" in prompt
    assert rating_candidates_prompt(note, regenerate=True).endswith(
        "콕 집어 다시 10줄 쓰시오."
    )


# T130-P1-B ------------------------------------------------------------------------------

def test_candidates_parse_many_numberings_drop_duplicates_and_stop_at_ten() -> None:
    text = "\n".join([
        "1. **요약창섭의 떡밥 한줄 평가** : 라면 국물로 철학 토론을 벌였구려 🍜",
        "2) 요약창섭의 떡밥 한줄 평가 : 고장 원인은 못 찾고 손가락질만 잘하오 👉",
        "3 - **요약창섭의 떡밥 한줄 평가**: 노래 고르다 해 떨어지겠소 🎤",
        "- **요약창섭의 떡밥 한줄 평가** : 라면 국물로 철학 토론을 벌였구려 🍜",
        "평가 없이 머리말만 빠진 줄이오",
        "**요약창섭의 떡밥 한줄 평가** : ",
        *(f"{n}. **요약창섭의 떡밥 한줄 평가** : 후보 {chr(0xAC00 + n)}이오" for n in range(4, 20)),
    ])
    found = parse_candidates(text)
    assert len(found) == 10
    assert found[0] == RATING_LABEL + "라면 국물로 철학 토론을 벌였구려 🍜"
    assert found[1] == RATING_LABEL + "고장 원인은 못 찾고 손가락질만 잘하오 👉"
    assert found[2] == RATING_LABEL + "노래 고르다 해 떨어지겠소 🎤"
    assert len(set(found)) == 10
    assert parse_candidates("평가가 없소") == []


@pytest.mark.parametrize(("content", "ok"), [
    ("라면 국물 하나로 철학 토론을 벌였구려 🍜", True),
    ("부산 여행 계획에 침 흘리는 꼴이오", True),            # the city is a topic word
    ("튀김 하나에 목숨 거는 꼴이오", True),
    ("화제가 이리저리 튀는 판이오", False),
    ("왔다갔다 하는 꼴이 볼만하오", False),
    ("오락가락하는 판이오", False),
    ("정신없는 판이오", False),
    ("부산스럽기 짝이 없소", False),
    ("요란한 하루였소", False),
    ("한 상 가득 차린 떡밥이오", False),
    ("뒤엉킨 실타래 같은 판이오", False),
    ("가람의 헛소리가 장관이오", False),                     # a speaker's name
    ("3시간 떠든 보람이 없소", False),                       # a number
    ("병신 같은 떡밥이오", False),                           # group slur
    ("마무리는 늘 다음으로 미루는 판이오", False),            # mocks unfinished talk
    ("P2의 떡밥이 웃기오", False),                           # internal key
    ("Too loud.", False),
    ("", False),
])
def test_candidate_filters(content, ok) -> None:
    assert usable_rating(RATING_LABEL + content, ["합성 원문"], ["가람", "나래"]) is ok


def test_zero_valid_candidates_is_distinguishable() -> None:
    bad = parse_candidates("1. **요약창섭의 떡밥 한줄 평가** : 정신없는 판이오\n2. 요란한 판이오\n평가 없음")
    assert len(bad) == 2 and filter_candidates(bad, [], []) == []


def test_numbered_lines_without_the_label_and_a_fullwidth_colon_are_read() -> None:
    found = parse_candidates("1. 라면 하나로 철학 토론을 벌였구려\n2) **요약창섭의 떡밥 한줄 평가**： 튀김에 목숨 거는 꼴이오\n"
                             "```\n이유: 설명 줄\n")
    assert found == [RATING_LABEL + "라면 하나로 철학 토론을 벌였구려", RATING_LABEL + "튀김에 목숨 거는 꼴이오"]
    assert banned_angle(RATING_LABEL + "화제를 돌리기 바쁘구려")


@pytest.mark.parametrize(("answer", "count", "expected"), [
    ("비슷함: 1, 3\n선택: 2", 3, (frozenset({1, 3}), 2)),
    ("비슷함: 없음\n선택: 4", 4, (frozenset(), 4)),
    ("비슷함: 1 2\n선택: 없음", 2, (frozenset({1, 2}), None)),
    ("선택: 2\n비슷함: 없음", 2, (frozenset(), 2)),
    ("비슷함: 1\n선택: 1", 2, None),       # picked a similar one
    ("비슷함: 없음\n선택: 9", 3, None),     # out of range
    ("비슷함: 없음", 3, None),
    ("2번이 제일 낫소", 3, None),
    ("비슷함: 일\n선택: 2", 3, None),
])
def test_judge_answer_format(answer, count, expected) -> None:
    assert parse_judgement(answer, count) == expected


def test_recent_ratings_keep_twenty_within_retention_per_channel(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    SQLiteWatchStore(path).replace(1, frozenset({10, 11}))
    clock = [NOW]
    store = SQLiteRecentRatings(path, retention_days=7, clock=lambda: clock[0])
    for n in range(25):
        assert store.add(1, 10, f"{RATING_LABEL}평가 {n}", posted_at=NOW + timedelta(seconds=n))
    store.add(1, 11, f"{RATING_LABEL}다른 채널", posted_at=NOW)
    recent = store.recent(1, 10)
    assert len(recent) == RECENT_LIMIT and recent[0].endswith("평가 24") and recent[-1].endswith("평가 5")
    assert store.recent(1, 11) == [f"{RATING_LABEL}다른 채널"]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM recent_ratings WHERE channel_id=10").fetchone() == (20,)
    clock[0] = NOW + timedelta(days=8)
    assert store.recent(1, 10) == []
    assert store.prune() == 21
    assert not store.add(1, 99, "주시하지 않는 채널", posted_at=NOW)


def count(path: Path, table: str) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_unwatch_guild_removal_orphans_backup_and_f02_f10_coexistence(tmp_path) -> None:
    path = tmp_path / "db.sqlite"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({10, 11}))
    watches.replace(2, frozenset({20}))
    messages = SQLiteMessageStore(path, clock=lambda: NOW)
    base = 1_400_000_000_000_000_000
    messages.upsert(MessageRecord(base + 1, 1, 10, 7, "가람", "원문", NOW - timedelta(minutes=2)), cached_at=NOW)
    messages.upsert(MessageRecord(base + 2, 1, 10, 8, "나래", "답", NOW - timedelta(minutes=1),
                                  is_reply=True, reply_to_message_id=base + 1), cached_at=NOW)
    store = SQLiteRecentRatings(path, clock=lambda: NOW)
    for guild, channel in ((1, 10), (1, 11), (2, 20)):
        store.add(guild, channel, f"{RATING_LABEL}평가", posted_at=NOW)
    assert (count(path, "recent_ratings"), count(path, "message_reply_refs"),
            count(path, "backfill_progress")) == (3, 1, 3)
    with closing(sqlite3.connect(path)) as connection:
        texts = [row[0] for row in connection.execute("SELECT text FROM recent_ratings")]
    assert all("원문" not in text and str(base) not in text for text in texts)
    backup = backup_settings(path, tmp_path / "backups")
    assert "평가" not in backup.read_text() and "recent" not in json.dumps(sorted(json.loads(backup.read_text())))
    watches.replace(1, frozenset({10}))
    assert store.recent(1, 11) == [] and count(path, "recent_ratings") == 2
    watches.remove_channel(1, 10)
    assert count(path, "recent_ratings") == 1
    assert (count(path, "message_reply_refs"), count(path, "backfill_progress")) == (0, 1)
    watches.remove_guild(2)
    assert (count(path, "recent_ratings"), count(path, "backfill_progress")) == (0, 0)
    # An older release unwatches with plain SQL; opening the store again prunes the rows.
    watches.replace(3, frozenset({30}))
    store.add(3, 30, f"{RATING_LABEL}평가", posted_at=NOW)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("DELETE FROM watched_channels WHERE guild_id=3")
    SQLiteWatchStore(path)
    assert count(path, "recent_ratings") == 0


def test_emoji_before_the_label_and_bold_wrapped_lines() -> None:
    found = parse_candidates("1. 🛠️ **요약창섭의 떡밥 한줄 평가** : 롤백 질문 하나에 빈칸이 드러났구려\n"
                             "2. **🤷 모르겠다 한마디로 결정을 떠넘겼구려**")
    assert found == [RATING_LABEL + "🛠️ 롤백 질문 하나에 빈칸이 드러났구려",
                     RATING_LABEL + "🤷 모르겠다 한마디로 결정을 떠넘겼구려"]
    custom = rating_candidates_prompt(tone="보고서체로 쓰시오")
    assert "하오체로 끝내시오" not in custom and "서버 말투·성격의 문체와 어미로 끝내시오" in custom
    assert "하오체로 끝내시오" in rating_candidates_prompt()
