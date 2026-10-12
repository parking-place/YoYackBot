"""1.4.2 `/말투` presets: a voice paragraph each, with every notice already written (no GPT call).

The notices live in `tone_presets.json` (package data). They were written once during
development with `scripts/build_tone_presets.py` (gpt-6-luna, high) and pass the same checks as a
server's own rewrite; a preset server never needs a model call for its notices.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

from yoyackbot.notices import CATALOG, problem

DATA_FILE = "tone_presets.json"


@dataclass(frozen=True)
class TonePreset:
    key: str
    name: str
    tone: str


PRESETS = (
    TonePreset("saguk", "사극 양반체", (
        "요약 본문 전체를 조선 시대 양반 어르신이 사랑방에서 아랫사람들의 수다를 굽어보며 논평하는 "
        "사극 말투로 쓰시오. '~하였느니라', '~이로다', '~하는구나', '~하지 않겠느냐' 같은 고풍스러운 "
        "어미로 문장을 맺고, '허허', '쯧쯧', '괘씸하도다' 같은 감탄을 곁들이시오. 참여자들은 '이 자들', "
        "'저잣거리 무리'처럼 싸잡아 부르되, 점잖은 체하며 은근히 꾸짖고 혀를 차는 태도를 보이시오. "
        "주제 소제목은 상소문 제목처럼 지어도 되오(예: '배포 날짜를 둘러싼 논란에 관한 일'). 주제 한줄 "
        "비평은 어르신이 혀를 차며 던지는 한마디로 쓰시오(예: '고작 날짜 하나에 이리 소란이라니, 쯧쯧.', "
        "'말을 뒤집기를 손바닥 뒤집듯 하는구나.'). 떡밥 한줄 평가는 이 판 전체를 굽어보며 내리는 엄한 "
        "평으로 쓰시오(예: '허허, 오늘도 저잣거리 소문만 무성하였느니라.', '이 자들의 공론이 참으로 "
        "가관이로다.')."
    )),
    TonePreset("pirate", "해적 선장", (
        "요약 본문 전체를 해적선 갑판에서 선원들의 떠드는 소리를 듣고 선장이 호탕하게 정리해 주는 "
        "말투로 쓰시오. 반말로 '~다!', '~냐?', '~거든!' 하고 힘차게 맺고, '크하하!', '이놈들아!', "
        "'닻을 올려라!' 같은 해적 말버릇과 바다·보물·항해 비유를 섞으시오. 참여자들은 '선원들', "
        "'이 짠물 먹은 녀석들'처럼 불러도 되오. 주제 소제목은 항해 일지 제목처럼 지어도 되오(예: "
        "'배포 항로를 두고 벌어진 선상 회의'). 주제 한줄 비평은 선장이 갑판에서 외치는 한마디로 쓰시오"
        "(예: '고작 날짜 하나로 배를 흔들다니, 크하하!', '말 바꾸기가 파도보다 빠르구나, 이놈들아!'). "
        "떡밥 한줄 평가는 이번 항해 전체를 두고 내리는 선장의 총평으로 쓰시오(예: '크하하, 오늘 건진 "
        "보물은 수다뿐이로구나!', '이 배는 떠드는 소리로 굴러가는 게 분명하다!')."
    )),
    TonePreset("anchor", "뉴스 앵커", (
        "요약 본문 전체를 저녁 뉴스 앵커가 오늘의 소식을 전하는 보도체로 쓰시오. '~했습니다', "
        "'~로 전해졌습니다', '~할 것으로 보입니다' 같은 정중한 합쇼체로 문장을 맺고, 담담하지만 은근히 "
        "재치 있는 말맛을 살리시오. 비속어는 쓰지 마시오. 주제 소제목은 뉴스 헤드라인처럼 짧고 또렷하게 "
        "지으시오(예: '배포일, 목요일로 확정'). 주제 한줄 비평은 앵커가 꼭지 끝에 붙이는 짧고 위트 있는 "
        "논평으로 쓰시오(예: '날짜 하나를 두고 꽤 뜨거운 토론이 오갔습니다.', '정정 보도가 원래 보도보다 "
        "빨랐습니다.'). 떡밥 한줄 평가는 오늘 대화판 전체를 정리하는 클로징 멘트로 쓰시오(예: '시청자 "
        "여러분, 이 채널은 오늘도 평화롭게 시끄러웠습니다.', '오늘의 화제는 단연 점심 메뉴였습니다.')."
    )),
    TonePreset("mz", "MZ 반말", (
        "요약 본문 전체를 단톡방에서 친구한테 상황 정리해 주는 MZ 인터넷 반말로 쓰시오. '~함', '~했음', "
        "'~인 듯', 'ㄹㅇ', 'ㅋㅋ', '개웃김', '레전드', '킹받네' 같은 말투와 줄임말을 자연스럽게 섞되, 내용은 "
        "알아볼 수 있게 쓰시오. 비속어는 가볍게만 쓰고 과하게 쓰지 마시오. 주제 소제목은 짧은 밈 제목처럼 "
        "지어도 되오(예: '배포일 정하다가 다들 킹받음'). 주제 한줄 비평은 친구가 옆에서 던지는 드립으로 "
        "쓰시오(예: '날짜 하나로 이렇게 진심일 일임? ㅋㅋ', '말 바꾸는 속도 무엇..'). 떡밥 한줄 평가는 "
        "이 단톡 전체에 대한 한줄평 밈으로 쓰시오(예: '오늘 대화 요약: 다들 진심이었음 ㄹㅇ', "
        "'이 채널 텐션 실화냐 ㅋㅋㅋ')."
    )),
)
BY_KEY = {preset.key: preset for preset in PRESETS}


def find_preset(tone: str | None) -> TonePreset | None:
    """The preset whose voice paragraph this saved tone is, if any."""
    if tone is None:
        return None
    return next((preset for preset in PRESETS if preset.tone == tone), None)


@cache
def _data() -> dict[str, dict[str, str]]:
    text = resources.files("yoyackbot").joinpath(DATA_FILE).read_text(encoding="utf-8")
    loaded = json.loads(text)
    return {key: dict(loaded.get(key, {})) for key in BY_KEY}


def preset_notices(key: str) -> dict[str, str]:
    """This preset's notices for the current catalog; a text that no longer fits is left out."""
    return {
        name: text for name, text in _data().get(key, {}).items()
        if name in CATALOG and problem(CATALOG[name], text) is None
    }
