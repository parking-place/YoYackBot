"""The closing '요약창섭의 떡밥 한줄 평가' line: prompt, format and position (T110a-P2)."""

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from yoyackbot.codex import CodexContract
from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, RangeRequest, RequestKind, SummaryMode, SummaryResult
from yoyackbot.input_files import InputWorkspace
from yoyackbot.ops import RequestMetrics
from yoyackbot.output_quality import RATING_LABEL, split_rating
from yoyackbot.summary_format import format_summary, utf16_length
from yoyackbot.summary_prompt import prompt_for

BODY = "**🚀 배포 일정**\n- **가람**: 목요일로 정정했소."
GOOD = f"{BODY}\n\n**요약창섭의 떡밥 한줄 평가** : 요일 퀴즈 풀다 날 샜단 말이오."
NOTICE = "(추가 요청 중 일부는 들어줄 수 없었소.)"


@pytest.mark.parametrize("mode", list(SummaryMode))
@pytest.mark.parametrize("retry", [{}, {"speaker_retry": True}, {"hate_retry": True}])
def test_every_prompt_asks_for_the_rating(mode: SummaryMode, retry: dict) -> None:
    prompt = prompt_for(mode, **retry)
    for phrase in ("떡밥 한줄 평가(기본)", "`**요약창섭의 떡밥 한줄 평가** : <평가>`",
                   "정확히 한 번", "한줄 비평", "하오체로 끝내시오",
                   "평가 줄 뒤에는 아무것도", "평가 줄이 있으면 그",
                   "추가 요청이 평가를 빼 달라고\n하면 평가 줄 없이 끝내시오"):
        assert phrase in prompt, phrase


@pytest.mark.parametrize(
    ("text", "body", "rating"),
    [
        (GOOD, BODY, RATING_LABEL + "요일 퀴즈 풀다 날 샜단 말이오."),
        (f"{BODY}\n\n요약창섭의 떡밥 한줄 평가 : 요란하오.", BODY, RATING_LABEL + "요란하오."),
        (f"{BODY}\n\n**요약창섭의 떡밥 한줄 평가**: 요란하오.", BODY, RATING_LABEL + "요란하오."),
        (BODY, BODY, None),
        (f"{BODY}\n\n**요약창섭의 떡밥 한줄 평가** : ", BODY, None),
        (f"**요약창섭의 떡밥 한줄 평가** : 먼저 나옴\n{BODY}", BODY, None),
        (f"{BODY}\n요약창섭의 떡밥 한줄 평가 : 첫째\n\n**요약창섭의 떡밥 한줄 평가** : 둘째",
         BODY, RATING_LABEL + "둘째"),
        (f"{BODY}\n{NOTICE}\n\n**요약창섭의 떡밥 한줄 평가** : 요란하오.", f"{BODY}\n{NOTICE}",
         RATING_LABEL + "요란하오."),
        (f"{BODY}\n\n**요약창섭의 떡밥 한줄 평가** : 요란하오.\n그리고 한 줄 더", f"{BODY}\n\n그리고 한 줄 더",
         None),
    ],
)
def test_rating_format_is_judged_and_normalized(text, body, rating) -> None:
    assert split_rating(text) == (body, rating)


def settings(tmp_path: Path) -> Settings:
    return Settings.from_environment({
        "DISCORD_BOT_TOKEN": "synthetic",
        "YOYACK_INPUT_DIRECTORY": str(tmp_path / "inputs"),
        "YOYACK_CODEX_AUTH_DIRECTORY": str(tmp_path / "model-auth"),
        "YOYACK_CODEX_EXECUTABLE": "/usr/local/bin/yoyack-codex",
    })


ROWS = [MessageRecord(1, 1, 10, 100, "가람", "금요일 배포 어때요?",
                      datetime(2026, 9, 30, 12, tzinfo=UTC))]


def engine(tmp_path: Path, answers: list[object], seen: list[tuple[str, list]]):
    class Runner:
        contract = CodexContract("/usr/local/bin/yoyack-codex", "gpt-6-luna", "low")

        async def execute(self, workspace: InputWorkspace, prompt: str) -> str:
            records = [json.loads(line) for line in workspace.log_file.read_text().splitlines()]
            seen.append((prompt, records))
            workspace.close()
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer  # type: ignore[return-value]

    return CodexSummaryEngine(settings(tmp_path), Runner())  # type: ignore[arg-type]


def test_rating_metric_is_allowlisted(caplog) -> None:
    caplog.set_level(logging.INFO)
    for value, logged in (("picked", "picked"), ("fallback_first", "fallback_first"),
                          ("retried", "none"), ("weird", "none")):
        metrics = RequestMetrics("time")
        metrics.rating = value
        metrics.rating_candidates = 12
        metrics.emit()
        assert f'"rating":"{logged}"' in caplog.text
    assert '"rating_candidates":10' in caplog.text


def test_rating_ends_the_last_message() -> None:
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    request = RangeRequest(RequestKind.TIME, now, start=now - timedelta(hours=1))
    body = "\n\n".join(f"**주제 {n}**\n- **가람**: " + "가" * 120 + "소." for n in range(20))
    text = f"{body}\n\n{RATING_LABEL}요일 퀴즈 풀다 날 샜단 말이오."
    parts = format_summary(request, ROWS, SummaryResult(text, "synthetic", 1),
                           ZoneInfo("Asia/Seoul"), posted_at=now)
    assert len(parts) > 1 and all(utf16_length(part) <= 1900 for part in parts)
    assert parts[-1].rstrip().endswith(f"{RATING_LABEL}요일 퀴즈 풀다 날 샜단 말이오.")
    assert all(RATING_LABEL not in part for part in parts[:-1])
