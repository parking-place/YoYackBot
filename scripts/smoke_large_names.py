"""Check nickname attribution above one hundred synthetic messages on a test LXC."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord


async def main() -> None:
    settings = Settings.from_environment()
    start = datetime(2026, 9, 29, tzinfo=UTC)
    messages = [MessageRecord(
        index, 1, 10, index % 2 + 1,
        ("새가람" if index > 80 else "가람") if index % 2 else "나래",
        ("자료를 점검하고 있소." if index % 2 else "검토를 계속하겠소.")
        if index < 119 else ("배포 날짜는 아직 미정이오." if index == 119
                             else "일정을 확인한 뒤 결정하겠소."),
        start + timedelta(seconds=index),
    ) for index in range(1, 121)]
    result = await CodexSummaryEngine.from_settings(settings).summarize(
        messages, channel_name="합성 대량 시험", range_label="최근 120개",
    )
    if (result.request_message_count != 120 or "새가람" not in result.text
            or "나래" not in result.text or "P1" in result.text or "P2" in result.text):
        raise AssertionError("Large synthetic nickname attribution failed")
    print(json.dumps({"messages": 120, "names": 2, "latest_name": True,
                      "internal_speaker_keys": False, "output_chars": len(result.text)},
                     sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
