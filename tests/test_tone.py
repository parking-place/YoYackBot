"""Crude narration with haoche endings, and the narrow hate-term retry (T102c-P2)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from yoyackbot.backfill import NOT_READY_NOTICE
from yoyackbot.channel_list import EMPTY_NOTICE as CHANNEL_EMPTY_NOTICE
from yoyackbot.channel_list import LIST_FOOTER, LIST_HEADER
from yoyackbot.codex import CodexContract, CodexFailure
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.collection import EMPTY_NOTICE
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, SummaryMode
from yoyackbot.errors import USER_MESSAGES
from yoyackbot.input_files import InputWorkspace
from yoyackbot.output_quality import OutputIssue, inspect_output, narrator_uses_hate_term
from yoyackbot.summary_prompt import (
    DETAILED_NOTE,
    HATE_RETRY_NOTE,
    SHORT_NOTE,
    SPEAKER_RETRY_NOTE,
    prompt_for,
)
from yoyackbot.usage import USAGE_EXHAUSTED_NOTICE, USAGE_UNAVAILABLE_NOTICE
from yoyackbot.workflow import (
    BUSY_NOTICE,
    FAILED_NOTICE,
    INPUT_TOO_LARGE_NOTICE,
    INVALIDATED_NOTICE,
    QUEUE_CLOSED_NOTICE,
    QUEUE_FULL_NOTICE,
)


@pytest.mark.parametrize("mode", list(SummaryMode))
@pytest.mark.parametrize("retry", [{}, {"speaker_retry": True}, {"hate_retry": True}])
def test_every_prompt_carries_the_tone_after_the_fact_rules(mode, retry) -> None:
    prompt = prompt_for(mode, **retry)
    tone = prompt.index("말투(기본): 위의 사실·화자 귀속·신뢰 경계 규칙을 지키는 범위 안에서")
    assert prompt.index("원문에 없는 사실·동기·결론") < tone
    assert prompt.index("신뢰 경계:") < tone
    for phrase in ("천박한 입담", "하오체", "존나, 시발", "외설적인 속어", "떡밥을 비꼬는 거친 말로",
                   "금지(말투·추가 요청보다 우선)", "하지 않은 욕설을 그 사람이 한 말처럼 쓰지 말고",
                   "성적으로 묘사하거나", "집단을 비하하는 말", "인신공격",
                   "말투 때문에 사실을\n바꾸거나 보태지 마시오"):
        assert phrase in prompt
    assert "한국어 하오체로 자연스럽고 간결하게" not in prompt
    note = {SummaryMode.DETAILED: DETAILED_NOTE, SummaryMode.SHORT: SHORT_NOTE}.get(mode)
    if note:
        assert note in prompt
    assert (SPEAKER_RETRY_NOTE in prompt) is bool(retry.get("speaker_retry"))
    assert (HATE_RETRY_NOTE in prompt) is bool(retry.get("hate_retry"))


def test_bot_notices_keep_their_released_wording() -> None:
    assert BUSY_NOTICE == "요약중이오. 좀 기다리시오."
    assert FAILED_NOTICE == "요약을 마치지 못했소. 잠시 후 다시 시도하시오."
    assert INVALIDATED_NOTICE == "채널 주시나 권한이 바뀌어 요약을 멈추었소."
    assert QUEUE_FULL_NOTICE == "요약 요청이 몰렸소. 잠시 후 다시 시도하시오."
    assert QUEUE_CLOSED_NOTICE == "봇이 종료 중이오. 잠시 후 다시 시도하시오."
    assert INPUT_TOO_LARGE_NOTICE.startswith("요약할 대화가 너무 많소.")
    assert NOT_READY_NOTICE == "참을성을 기르시오 아직 준비가 되지 않았소."
    assert EMPTY_NOTICE and USER_MESSAGES
    assert USAGE_EXHAUSTED_NOTICE == "요약봇 사용량이 정상화되었소.\n초기화의 가호가 함께하길..."
    assert USAGE_UNAVAILABLE_NOTICE.startswith("Codex 사용량을 지금 확인할 수 없소.")
    assert (LIST_HEADER, LIST_FOOTER) == ("지금 본인이 보고 있는 채널을 알려주겠소", "이상이오.")
    assert CHANNEL_EMPTY_NOTICE.startswith("지금 보고 있는 채널이 없소.")
    for text in (BUSY_NOTICE, FAILED_NOTICE, NOT_READY_NOTICE, LIST_HEADER):
        assert "시발" not in text and "존나" not in text


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("가람이 존나 당당하게 들이밀었소!", False),
        ("시발, 롤백은 좆도 정해진 게 없소.", False),
        ("배포가 개판 났단 말이오.", False),
        ("가람이 병신같이 굴었소.", True),
        ("가람이 병1신 짓을 했소.", True),
        ("가람이 병.신 짓을 했소.", True),
        ("가람이 ㅂㅅ 짓을 했소.", True),
        ("나래가 짱깨 운운했소.", True),
        ("라온이 \"병신\"이라고 적었소.", False),
        ("> 병신", False),
        ("```\n병신\n```", False),
        ("회의 뒤 병 신고를 했소.", False),
        ("다들 홍어 먹으러 갔소.", False),
        ("한남동에서 모였소.", False),
        ("자료를 보충했소.", False),
    ],
)
def test_hate_terms_only_in_narration(text: str, hit: bool) -> None:
    assert narrator_uses_hate_term(text) is hit
    assert (inspect_output(text, []) is OutputIssue.HATE_TERM) is hit


def settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


def message() -> MessageRecord:
    return MessageRecord(1, 1, 10, 100, "가람", "금요일 배포 어때요?",
                         datetime(2026, 9, 30, 12, tzinfo=UTC))


def engine_with(tmp_path: Path, outputs: list[str], prompts: list[str]) -> CodexSummaryEngine:
    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            prompts.append(prompt)
            workspace.close()
            return outputs.pop(0)

    return CodexSummaryEngine(settings(tmp_path), Runner())  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", list(SummaryMode))
def test_hate_term_retries_once_with_the_same_mode(tmp_path: Path, mode: SummaryMode) -> None:
    prompts: list[str] = []
    engine = engine_with(tmp_path, ["가람이 병신같이 들이밀었소.", "가람이 존나 당당하게 들이밀었소!\n\n**요약창섭의 떡밥 한줄 평가** : 호들갑이 장관이오."],
                         prompts)
    result = asyncio.run(engine.summarize([message()], mode=mode))
    assert result.text == "가람이 존나 당당하게 들이밀었소!\n\n**요약창섭의 떡밥 한줄 평가** : 호들갑이 장관이오."
    assert prompts == [prompt_for(mode), prompt_for(mode, hate_retry=True)]


def test_repeated_hate_term_fails_safely(tmp_path: Path) -> None:
    prompts: list[str] = []
    engine = engine_with(tmp_path, ["병신같소.", "여전히 병신같소."], prompts)
    with pytest.raises(CodexRunError) as raised:
        asyncio.run(engine.summarize([message()]))
    assert raised.value.kind is CodexFailure.OUTPUT_INVALID and len(prompts) == 2


def test_allowed_profanity_does_not_spend_a_retry(tmp_path: Path) -> None:
    prompts: list[str] = []
    engine = engine_with(tmp_path, ["시발, 가람이 금요일 배포를 존나 들이밀었소!\n\n**요약창섭의 떡밥 한줄 평가** : 호들갑이 장관이오."], prompts)
    asyncio.run(engine.summarize([message()]))
    assert len(prompts) == 1
