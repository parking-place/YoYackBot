"""Separate internal failure categories from user-facing messages."""

from enum import Enum


class FailureKind(Enum):
    UNWATCHED = "unwatched"
    INVALID_OPTION = "invalid_option"
    EMPTY = "empty"
    HISTORY = "history"
    MODEL = "model"
    SEND = "send"
    BUSY = "busy"
    COOLDOWN = "cooldown"


USER_MESSAGES: dict[FailureKind, str] = {
    FailureKind.UNWATCHED: "이 채널은 아직 살피고 있지 않소. `/채널 설정`으로 먼저 정하시오.",
    FailureKind.INVALID_OPTION: "그 명은 알아듣기 어렵소. `!!요약좀 도움`에서 사용법을 살펴보시오.",
    FailureKind.EMPTY: "요약할 만한 대화가 없소.",
    FailureKind.HISTORY: "대화를 불러오지 못하였소. 잠시 뒤 다시 시도하시오.",
    FailureKind.MODEL: "요약에 실패하였소. 잠시 뒤 다시 명하시오.",
    FailureKind.SEND: "요약을 전하지 못하였소. 잠시 뒤 다시 시도하시오.",
    FailureKind.BUSY: "요약중이오. 좀 기다리시오.",
    FailureKind.COOLDOWN: "아직은 때가 아니오. 잠시 뒤에 오시오.",
}


def message_for(kind: FailureKind) -> str:
    return USER_MESSAGES[kind]
