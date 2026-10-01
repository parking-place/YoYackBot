"""Emoji everywhere, one critique per topic, and a terse short layout (T112-P1)."""

import pytest

from yoyackbot.domain import SummaryMode
from yoyackbot.output_quality import RATING_LABEL, narrator_mocks_ongoing, split_rating
from yoyackbot.parser import wants_no_rating
from yoyackbot.summary_prompt import (
    DETAILED_NOTE,
    RATING_PROMPT,
    REQUEST_PRIORITY_NOTE,
    SHORT_NOTE,
    SUMMARY_PROMPT,
    prompt_for,
)

VARIANTS = [{}, {"speaker_retry": True}, {"hate_retry": True}, {"ongoing_retry": True},
            {"note": "시간순으로 해줘"}]


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("mode", list(SummaryMode))
@pytest.mark.parametrize("variant", VARIANTS)
def test_every_prompt_has_emoji_and_topic_critique_rules(mode: SummaryMode, variant: dict) -> None:
    text = flat(prompt_for(mode, **variant))
    for phrase in ("이모지(기본): 이모지를 제한 없이 마음껏, 적극적으로 써서 읽기 쉽고 재미있게 하시오.",
                   "주제 소제목은 반드시 이모지로 시작하고",
                   "내용 줄·불릿·주제 한줄 비평·떡밥 한줄 평가에도 줄마다 하나 이상 섞으시오.",
                   "개수와 위치에는 제한이 없소.",
                   "계획·일정이 아직 안 잡혔다는 점은 비평 소재로도 쓰지 마시오",
                   "화자 이름· 숫자·시간·금액 글자 사이에 끼워 넣지 말고",
                   "찬성·반대·결정 같은 사실을 이모지로 대신하지 말고 글로 쓰며",
                   "주제 묶음마다 **정확히 한 줄**을 그 묶음 맨 끝에 `↳ *한줄 비평*` 형태로 따로 쓰시오.",
                   "비평 줄이 빠진 주제가 하나도 없어야 하오.",
                   "`⏳ 진행 중인 거` 묶음에는 비평 줄을 붙이지 마시오.",
                   "짧고 신랄한 한 문장(40자 안팎)",
                   "평가 문장에는 이모지를 마음껏 써도 되오."):
        assert phrase in text, phrase
    assert "최대 한 줄" not in text and "이모지 1개까지" not in text


@pytest.mark.parametrize("mode", list(SummaryMode))
def test_only_short_drops_speaker_bullets(mode: SummaryMode) -> None:
    text = prompt_for(mode)
    short_only = ("짧게에서는 화자별 불릿을 쓰지 말고", "그 주제의 내용만 1~2줄", "짧게 형식 예")
    for phrase in short_only:
        assert (phrase in text) is (mode is SummaryMode.SHORT), phrase
    assert "길게·자세히에서는 묶음 안에 `- **화자 이름**: 한\n말이나 한 일` 불릿을 쓰되" in text
    assert "불릿은 모두 합쳐" not in text and "8개 이하" not in text


def test_short_layout_details() -> None:
    text = flat(SHORT_NOTE)
    for phrase in ("누가 했는지가 중요한 곳(결정·담당·정정·제안자)에만 이름을 쓰고",
                   "서로 다른 사람의 의견을 한 사람 말처럼 합치지 마시오.",
                   "'찬반이 갈렸소'처럼 귀속 없이 적으시오.",
                   "결정은 `✅ **결정**:`, 진행 중인 것은 `⏳ **진행 중**:`으로",
                   "주제당 내용 2줄을 넘기지 마시오.",
                   "↳ *면 하나 고르는 데 청문회를 차렸구려* 🙄🔥"):
        assert phrase in text, phrase
    assert "`⏳ 진행 중` 같은 소제목을 절대 쓰지 말고, 결정·진행 중은 해당 주제의 내용 줄 안에만 표시하시오" in text
    assert "1~2줄" not in DETAILED_NOTE and "불릿 수에 제한은 없소" in DETAILED_NOTE
    # The format example must not itself mock unfinished talk.
    assert not narrator_mocks_ongoing(SHORT_NOTE)


def test_requests_can_drop_emoji_or_topic_critiques_but_not_the_rating_by_accident() -> None:
    text = flat(REQUEST_PRIORITY_NOTE)
    assert "'이모지 빼고': 이모지를 하나도 쓰지 마시오(결정·진행 중 표시도 글자로만)." in text
    assert "'비평 빼줘'/'비아냥 빼줘': 주제 한줄 비평 줄 없이 쓰되 떡밥 한줄 평가는 유지." in text
    assert "추가 요청이 이모지를 빼 달라고 하면 이모지를 하나도 쓰지 마시오." in flat(SUMMARY_PROMPT)
    for note in ("비평 빼줘", "비아냥 빼줘", "이모지 빼고"):
        assert not wants_no_rating(note), note
    assert wants_no_rating("평가 빼줘")
    assert ("표현 요청뿐이면 이 안내 줄을 절대 붙이지 마시오." in text)


@pytest.mark.parametrize("rating", ["🔥 달력 한 장에 요란 떨 일이오? 🙄🤦‍♂️", "요란하오 👏🏽👏🏽"])
def test_emoji_rating_line_still_splits(rating: str) -> None:
    body = "**🚀 배포 날짜** 🗓️\n목요일로 정했소. ✅ **결정**: 목요일 🎉\n↳ *요일 퀴즈였소* 🤡"
    assert split_rating(f"{body}\n\n{RATING_LABEL}{rating}") == (body, RATING_LABEL + rating)
    assert "이모지를 마음껏" in RATING_PROMPT
