"""Narration that sneers at unfinished talk is caught and retried once (T111a-P2)."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rating_fakes import candidates, is_rating_step, skip_rating_step

from yoyackbot.codex import CodexContract
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import InputWorkspace
from yoyackbot.ops import RequestMetrics
from yoyackbot.output_quality import (
    CRITIQUE_JAB_TERMS,
    ONGOING_JAB_TERMS,
    inspect_output,
    narrator_mocks_ongoing,
)
from yoyackbot.summary_prompt import ONGOING_RETRY_NOTE, RATING_LABEL

BODY = "**🗳️ 규칙 투표**\n- **서하**: 투표를 누가 여는지 물었소.\n- **이안**: 내일 열겠다고 했소."
JAB_BODY = BODY + "\n↳ *투표 하나 여는 것도 질질 끄는구려.*"
RATING = RATING_LABEL + "떡밥 하나에 다들 침 튀기며 달려드는 꼴이 장관이오."
JAB_RATING = RATING_LABEL + "마무리는 늘 다음으로 미루는 판이오."
ROWS = [MessageRecord(1, 1, 10, 100, "서하", "투표 누가 열어요?", datetime(2026, 10, 1, 12, tzinfo=UTC))]
JABS = [
    "- **이안**: 또 질질 끌었소.", "결국 다음으로 미뤘구려.", "늘 미루기만 하오.", "다음 주로 미뤄 버렸소.",
    "미룬 게 한두 번이오?", "여전히 제자리걸음이오.", "계획은 헛바퀴만 도오.", "흐지부지 끝났소.",
    "용두사미가 따로 없소.", "숙제로 남겼구려.", "끝맺음이 영 시원찮소.", "마무리는 늘 그 모양이오.",
    "결론도 없이 떠들었소.", "역시 아무것도 안 정했단 말이오!", "정한 게 없구려.", "판이 참 싱겁구려.",
    "↳ *또 질질 끄는구려.*", JAB_RATING,
    "↳ *담당을 묻자 다음 회의 얘기부터 꺼내는군* 🙄", "↳ *숙소 얘긴 감으로도 못 박았구려!*",
    "↳ *답은 아직 안개 속이구려* 🤔", "↳ *문구부터 쓰고 나중에 보자니 제멋대로구려*",
    RATING_LABEL + "아직도 정한 건 감감하구려.",
]
CALM = [
    "- **민준**: 안내 여부는 다음 날 다시 보자고 했소.", "**진행 중**: 투표는 아직 열리지 않았소.",
    "**진행 중인 거**", "- 아직 얘기 중이오.", "- **가람**: 금요일 대신 목요일로 정정했소.",
    "- **가람**: 다음 회의에서 이야기하자고 했소.", "⏳ **진행 중**: 숙소 위치는 아직 미정이오.",
    "↳ *숙소 질문에 돌아온 건 모른다 한마디뿐이오* 🤷",
]
QUOTED = [
    '- **나래**: "또 질질 끄네"라고 했소.', "> 결국 미뤘네", "```\n흐지부지\n```",
    "- **도하**: “숙제로 남겨두자”고 했소.",
]


def test_every_listed_term_is_caught() -> None:
    assert len(ONGOING_JAB_TERMS) == len(set(ONGOING_JAB_TERMS)) == 16
    for term in ONGOING_JAB_TERMS:
        assert narrator_mocks_ongoing(f"- 서술자가 {term} 했소."), term
    for term in CRITIQUE_JAB_TERMS:
        assert narrator_mocks_ongoing(f"↳ *{term} 그 꼴이오*"), term
        assert not narrator_mocks_ongoing(f"- **가람**: {term} 얘기했소."), term


@pytest.mark.parametrize("text", JABS)
def test_narration_jabs_are_detected(text: str) -> None:
    assert narrator_mocks_ongoing(text)


@pytest.mark.parametrize("text", CALM + QUOTED)
def test_calm_and_quoted_lines_are_not(text: str) -> None:
    assert not narrator_mocks_ongoing(text)


def test_jab_is_not_an_output_failure() -> None:
    assert inspect_output(JAB_BODY, []) is None


def settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


def run(tmp_path: Path, answers: list[str], *, ratings: list[str] | None = None, **kwargs):
    """Summary calls answer from `answers`; the rating step answers from `ratings` or is
    unavailable, in which case the summary's own (usable) rating line is kept."""
    seen: list[tuple[str, list]] = []

    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            if ratings is None:
                skip_rating_step(workspace, prompt)
            records = [json.loads(line) for line in workspace.log_file.read_text().splitlines()]
            seen.append((prompt, records))
            workspace.close()
            if is_rating_step(prompt):
                return ratings.pop(0)  # type: ignore[union-attr]
            return answers.pop(0)

    engine = CodexSummaryEngine(settings(tmp_path), Runner())  # type: ignore[arg-type]
    return asyncio.run(engine.summarize(ROWS, **kwargs)), seen


def test_clean_summary_needs_one_summary_call(tmp_path: Path) -> None:
    result, seen = run(tmp_path, [f"{BODY}\n\n{RATING}"])
    assert (result.ongoing_jab, result.rating, len(seen)) == ("none", "fallback_summary", 1)


def test_body_jab_retries_the_whole_summary_once(tmp_path: Path) -> None:
    result, seen = run(tmp_path, [f"{JAB_BODY}\n\n{RATING}", f"{BODY}\n\n{RATING}"],
                       request_note="시간순으로 해줘")
    assert result.text == f"{BODY}\n\n{RATING}" and len(seen) == 2
    assert (result.ongoing_jab, result.rating) == ("retried", "fallback_summary")
    assert seen[1][0].endswith(ONGOING_RETRY_NOTE) and "«시간순으로 해줘»" in seen[1][0]
    assert seen[0][1] == seen[1][1]


def test_a_mocking_rating_is_never_posted(tmp_path: Path) -> None:
    # The summary's own line mocks unfinished talk; candidates drop the jab and the judge picks.
    result, seen = run(
        tmp_path, [f"{BODY}\n\n{JAB_RATING}"],
        ratings=[candidates(JAB_RATING.removeprefix(RATING_LABEL), "투표 하나에 웅변대회를 열었구려."),
                 "비슷함: 없음\n선택: 1"],
    )
    assert result.text == f"{BODY}\n\n{RATING_LABEL}투표 하나에 웅변대회를 열었구려."
    assert result.rating == "picked" and len(seen) == 3
    assert result.rating_candidates == 1


def test_jab_left_after_retries_is_counted_and_its_rating_dropped(tmp_path: Path) -> None:
    result, seen = run(tmp_path, [f"{JAB_BODY}\n\n{JAB_RATING}", f"{JAB_BODY}\n\n{JAB_RATING}"])
    assert len(seen) == 2 and result.text == JAB_BODY
    assert (result.ongoing_jab, result.rating) == ("retried_left", "missing")


def test_invalid_retry_keeps_the_first_answer(tmp_path: Path) -> None:
    result, seen = run(tmp_path, [f"{JAB_BODY}\n\n{RATING}", "YOYACK_INPUT_UNAVAILABLE"])
    assert result.text == f"{JAB_BODY}\n\n{RATING}" and len(seen) == 2
    assert result.ongoing_jab == "retried_left"


def test_hate_retry_takes_the_slot(tmp_path: Path) -> None:
    result, seen = run(tmp_path, ["가람이 병신같이 굴었소.", JAB_BODY])
    assert len(seen) == 2 and "앞선 응답에 집단을 비하하는 말" in seen[1][0]
    assert ONGOING_RETRY_NOTE not in seen[1][0]
    assert (result.rating, result.ongoing_jab) == ("missing", "retried_left")


def test_skipped_rating_never_asks_for_candidates(tmp_path: Path) -> None:
    result, seen = run(tmp_path, [f"{BODY}\n\n{JAB_RATING}"], request_note="평가 빼줘", ratings=[])
    assert result.text == BODY and len(seen) == 1
    assert (result.rating, result.ongoing_jab) == ("skipped", "none")


def test_metric_is_allowlisted_and_has_no_text(caplog) -> None:
    caplog.set_level(logging.INFO)
    for value, logged in (("retried", "retried"), ("retried_left", "retried_left"), ("x", "none")):
        metrics = RequestMetrics("time")
        metrics.ongoing_jab = value
        metrics.emit()
        assert f'"ongoing_jab":"{logged}"' in caplog.text
    assert "질질" not in caplog.text
