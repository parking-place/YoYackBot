"""Included trigger detection and help routing, before range parsing."""

import re
from dataclasses import dataclass
from enum import Enum

TRIGGER = "!!요약좀"
HELP_WORD = re.compile(r"(?<!\S)도움(?:말)?(?=\s|$)")

HELP_TEXT = """📜 요약 사용법을 알려드리겠소.

`!!요약좀` — 최근 1시간의 대화를 요약하오.
`!!요약좀 3` — 최근 3시간의 대화를 요약하오.
`!!요약좀 30분` — 최근 30분의 대화를 요약하오.
`!!요약좀 2시간` — 최근 2시간의 대화를 요약하오.
`!!요약좀 100개` — 최근 일반 사용자 메시지 100개를 요약하오.
`!!요약좀 오늘` — 오늘 00시부터 지금까지의 대화를 요약하오.
`!!요약좀 2일` — 최근 2일간의 대화를 요약하오.
`!!요약좀 1주` — 최근 1주간의 대화를 요약하오.

숫자만 적으면 시간 단위로 알아듣겠소.
주시할 채널은 관리자가 `/채널 설정`에서 정하시오."""


class RouteKind(Enum):
    NONE = "none"
    HELP = "help"
    SUMMARY = "summary"


@dataclass(frozen=True)
class TriggerRoute:
    kind: RouteKind
    options: str = ""
    repeated: bool = False


def route_trigger(content: str) -> TriggerRoute:
    """Use the first trigger's options; help has priority across repeated triggers."""
    _, marker, after = content.partition(TRIGGER)
    if not marker:
        return TriggerRoute(RouteKind.NONE)
    repeated = TRIGGER in after
    options = after.partition(TRIGGER)[0].strip()
    if HELP_WORD.search(after):
        return TriggerRoute(RouteKind.HELP, repeated=repeated)
    return TriggerRoute(RouteKind.SUMMARY, options=options, repeated=repeated)
