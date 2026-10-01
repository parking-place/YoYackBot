"""Unfinished talk is ongoing, never a flaw to mock (T111a-P1)."""

import pytest

from yoyackbot.domain import SummaryMode
from yoyackbot.summary_prompt import (
    RATING_PROMPT,
    REQUEST_PRIORITY_NOTE,
    SUMMARY_PROMPT,
    prompt_for,
    rating_prompt,
)

PROMPTS = [
    prompt_for(mode, speaker_retry=speaker, hate_retry=hate, note=note)
    for mode in SummaryMode
    for speaker, hate in ((False, False), (True, False), (False, True))
    for note in (None, "시간순으로 해줘")
]
OLD_PHRASES = ("아직 안 정해진 거", "**미정**:", "질질 끄는 꼴", "아무것도 안 정했", "남은 건 하나도 없",
               "결정 난 게 없소", "미해결점", "남은 점")


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("prompt", PROMPTS)
def test_every_prompt_treats_unfinished_talk_as_ongoing(prompt: str) -> None:
    text = flat(prompt)
    for phrase in ("채널 대화는 끝난 회의가 아니라 계속 이어지는 대화이오.",
                   "완벽하게 매듭지어진 것만 결정이고",
                   "진행 중은 흠이 아니니 아직 이어지는 이야기로 담담하게 적고",
                   "아직 진행 중이라는 사실 자체는 비꼬지 마시오",
                   "아직 진행 중이라는 점은 비아냥 소재로 쓰지 마시오.",
                   "결론이 안 났다·미뤘다·제자리다·끝맺음이 없다는 식으로 평가하지 마시오.",
                   "`**⏳ 진행 중인 거**`"):
        assert phrase in text, phrase
    for phrase in OLD_PHRASES:
        assert phrase not in prompt, phrase


def test_short_marks_ongoing_inline() -> None:
    text = flat(prompt_for(SummaryMode.SHORT))
    assert "`결정 난 거`· `진행 중인 거` 묶음은 따로 만들지 마시오(" in text
    assert "진행 중인 것은 `⏳ **진행 중**:`으로 내용 줄 안에 짧게 표시하고" in text


def test_rating_prompt_does_not_mock_unfinished_talk() -> None:
    for prompt in (RATING_PROMPT, rating_prompt("욕 빼고")):
        text = flat(prompt)
        assert "결론이 안 났다· 미뤘다·제자리다·끝맺음이 없다는 식으로 평가하지 마시오." in text
        for phrase in OLD_PHRASES:
            assert phrase not in prompt, phrase


def test_decision_only_without_decisions_is_calm() -> None:
    text = flat(REQUEST_PRIORITY_NOTE)
    assert "'아직 매듭지어진 건 없고, 다들 얘기 중이오.'라고 쓰면 안 되고" in text
    assert "그 한 줄을 담담하게 쓰시오." in text


def test_snark_targets_actual_words_and_deeds() -> None:
    text = flat(SUMMARY_PROMPT)
    assert "말바꿈·헛짚음·딴소리·호들갑·뻔한 소리를 마음껏 비꼬고 빈정거리시오" in text
    assert "질질 끈다·미뤘다· 제자리걸음·흐지부지·끝맺음이 싱겁다 같은 말 금지" in text


def test_help_calls_unfinished_talk_ongoing() -> None:
    from yoyackbot.parser import HELP_TEXT

    assert "화자별 흐름과 결정·진행 중인 이야기까지 요약하오." in HELP_TEXT
    assert "남은 점" not in HELP_TEXT and len(HELP_TEXT) < 2000
