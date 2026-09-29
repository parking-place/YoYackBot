"""One nonposting synthetic model call for the 0.8.0 resource gate (LXC only)."""

import asyncio
from datetime import UTC, datetime, timedelta

from yoyackbot.codex_engine import CodexSummaryEngine
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord


async def main() -> None:
    settings = Settings.from_environment()
    now = datetime.now(UTC)
    records = [
        MessageRecord(1, 1, 1, 1, "가람", "합성 회의를 제안하오.", now - timedelta(minutes=2)),
        MessageRecord(2, 1, 1, 2, "나래", "일정을 확인한 뒤 답하겠소.", now - timedelta(minutes=1)),
    ]
    result = await CodexSummaryEngine.from_settings(settings).summarize(
        records, channel_name="합성", range_label="합성 2건"
    )
    assert result.request_message_count == 2 and result.text
    print("model_probe_pass")


if __name__ == "__main__":
    asyncio.run(main())
