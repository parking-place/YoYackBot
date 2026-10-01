"""Separate internal failure categories from user-facing messages."""

from enum import Enum

from yoyackbot.collection import EMPTY_NOTICE
from yoyackbot.parser import USAGE_NOTICE
from yoyackbot.watch_gate import UNWATCHED_NOTICE

BUSY_NOTICE = "⏳ 요약중이오. 좀 기다리시오. 🙏"


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
    # The same text the bot actually sends, so the two can never drift apart (1.1.3a).
    FailureKind.UNWATCHED: UNWATCHED_NOTICE,
    FailureKind.INVALID_OPTION: USAGE_NOTICE,
    FailureKind.EMPTY: EMPTY_NOTICE,
    FailureKind.HISTORY: "📂 대화를 불러오지 못하였소. 잠시 뒤 다시 시도하시오. 🔁",
    FailureKind.MODEL: "😵 요약에 실패하였소. 잠시 뒤 다시 명하시오. 🔁",
    FailureKind.SEND: "📮 요약을 전하지 못하였소. 잠시 뒤 다시 시도하시오. 🔁",
    FailureKind.BUSY: BUSY_NOTICE,
    FailureKind.COOLDOWN: "🧊 아직은 때가 아니오. 잠시 뒤에 오시오. ⏰",
}


def message_for(kind: FailureKind) -> str:
    return USER_MESSAGES[kind]
