"""Markdown-rich summaries, quoted topic critiques, underlined nicknames (T112a-P2)."""

import pytest

from yoyackbot.domain import SummaryMode
from yoyackbot.output_quality import narrator_mocks_ongoing
from yoyackbot.summary_prompt import (
    PROMPT_VERSION,
    RATING_CANDIDATES_PROMPT,
    SHORT_NOTE,
    prompt_for,
)

VARIANTS = [{}, {"speaker_retry": True}, {"hate_retry": True}, {"ongoing_retry": True},
            {"note": "이모지 빼고"}]


def flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("mode", list(SummaryMode))
@pytest.mark.parametrize("variant", VARIANTS)
def test_every_prompt_asks_for_markdown(mode: SummaryMode, variant: dict) -> None:
    text = flat(prompt_for(mode, **variant))
    for phrase in (
        "이모지로 시작하는 `###` 제목 한 줄(`### 🚀 주제 이름`)",
        "`### ✅ 결정 난 거`", "`### ⏳ 진행 중인 거`",
        "마크다운(기본): Discord 마크다운을 적극적으로 쓰시오.",
        "speaker_names 이름 그대로 밑줄 `__이름__`으로 쓰고(굵은 불릿에서는 `**__이름__**`)",
        "주제 한줄 비평과 떡밥 한줄 평가에는 이름을 쓰지 마시오.",
        "원문에서 실제로 정정·철회된 안만 취소선으로 보여 주시오(예: `~~금요일~~ → **목요일**`).",
        "`###`보다 큰 제목(`#`·`##`), 스포일러(`||`), 링크는 쓰지 마시오.",
        "마크다운은 강조일 뿐 사실이나 결정 여부를 바꾸지 않소.",
        "결정·핵심 숫자·시간·금액·기한은 적극적으로 굵게 강조하되",
        "인용문 `> ↳ _한줄 비평_ 이모지` 형태로 따로 쓰시오.",
        "원문을 인용할 때는 `> \"원문\"`처럼 따옴표를 붙이고, `> ↳`로 시작하는 줄은 비평 줄에만 쓰시오.",
    ):
        assert phrase in text, phrase
    for old in ("`↳ *한줄 비평*`", "`**🚀 주제 이름**`", "`**✅ 결정 난 거**`", "`>`는 원문 인용 전용",
                "'↳ *"):
        assert old not in text, old
    assert PROMPT_VERSION == "1.3.3-p4-v1"


def test_short_example_uses_the_new_markdown_with_synthetic_names() -> None:
    for line in ("### 🍜 점심 메뉴 🤤", "__해솔__이 ~~짜장 하나~~ 대신", "✅ **결정**: **반반 주문** 🥢",
                 "> ↳ _면 하나 고르는 데 청문회를 차렸구려_ 🙄🔥", "### 🎳 볼링 모임",
                 "> ↳ _공 굴릴 생각에 벌써 어깨부터 푸는 꼴이오_ 💪"):
        assert line in SHORT_NOTE, line
    assert "인용문 주제 한줄 비평 한 줄을 쓰시오" in flat(SHORT_NOTE)
    for real_case in ("가람", "나래", "다온", "지호", "한결", "보람"):
        assert real_case not in SHORT_NOTE
    assert not narrator_mocks_ongoing(SHORT_NOTE)


def test_rating_keeps_its_label_and_names_stay_out() -> None:
    assert "`번호. **요약창섭의 떡밥 한줄 평가** : <평가>`" in flat(RATING_CANDIDATES_PROMPT)
    assert "사람 이름·숫자·시간은 쓰지 마시오." in flat(RATING_CANDIDATES_PROMPT)
