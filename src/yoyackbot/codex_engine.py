"""Summarize request-scoped message records through the pinned Codex CLI."""

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from yoyackbot.codex import CodexContract, CodexContractError, CodexFailure
from yoyackbot.codex_runner import CodexRunError, SandboxedCodex
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, SummaryMode, SummaryResult
from yoyackbot.input_files import InputWorkspace, serialize_conversation
from yoyackbot.output_quality import (
    OutputIssue,
    inspect_output,
    narrator_mocks_ongoing,
    narrator_uses_hate_term,
    split_rating,
)
from yoyackbot.parser import wants_no_rating, wants_refusal_notice
from yoyackbot.summary_prompt import REFUSAL_NOTICE, prompt_for, rating_prompt


@dataclass(frozen=True)
class CodexSummaryEngine:
    settings: Settings
    runner: SandboxedCodex
    _slots: asyncio.Semaphore = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_slots", asyncio.Semaphore(self.settings.codex_concurrency))

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        contract = CodexContract.from_settings(settings)
        if not contract.version_matches():
            raise CodexContractError("Pinned Codex CLI version is unavailable")
        if not contract.authentication_ready(settings.codex_auth_directory):
            raise CodexContractError("Codex model account is not authenticated")
        return cls(settings, SandboxedCodex(
            contract, settings.codex_auth_directory / "auth.json",
            timeout_seconds=settings.codex_timeout_seconds,
            max_output_bytes=settings.max_output_bytes,
        ))

    async def summarize(
        self, messages: Sequence[MessageRecord], *, channel_name: str = "현재 채널",
        range_label: str = "요청 범위", trigger_message_id: int | None = None,
        on_input_size: Callable[[int], None] | None = None,
        mode: SummaryMode = SummaryMode.SHORT,
        request_note: str | None = None,
    ) -> SummaryResult:
        included = [item for item in messages if item.message_id != trigger_message_id]
        if not included:
            raise ValueError("Summary requires at least one eligible message")
        data = serialize_conversation(
            included, channel_name=channel_name, range_label=range_label,
            trigger_message_id=trigger_message_id, max_bytes=self.settings.max_input_bytes,
            on_size=on_input_size, request_note=request_note,
        )
        root = self.settings.input_directory.absolute()
        async with self._slots:
            workspace = InputWorkspace.create(root, data)
            skip_rating = request_note is not None and wants_no_rating(request_note)
            result = await self.runner.execute(
                workspace, prompt_for(mode, note=request_note, skip_rating=skip_rating)
            )
            source_bodies = [item.content for item in included]
            issue = inspect_output(result, source_bodies)
            ongoing = "none"
            if issue in (OutputIssue.SPEAKER_KEY, OutputIssue.HATE_TERM):
                retry_workspace = InputWorkspace.create(root, data)
                result = await self.runner.execute(retry_workspace, prompt_for(
                    mode, note=request_note, skip_rating=skip_rating,
                    speaker_retry=issue is OutputIssue.SPEAKER_KEY,
                    hate_retry=issue is OutputIssue.HATE_TERM,
                ))
            elif issue is None and narrator_mocks_ongoing(split_rating(result)[0]):
                ongoing = "retried"
                retry_workspace = InputWorkspace.create(root, data)
                retried = await self.runner.execute(retry_workspace, prompt_for(
                    mode, note=request_note, skip_rating=skip_rating, ongoing_retry=True,
                ))
                if inspect_output(retried, source_bodies) is None:
                    result = retried
            if inspect_output(result, source_bodies) is not None:
                raise CodexRunError(CodexFailure.OUTPUT_INVALID)
            body, rating = split_rating(result)
            if (
                request_note is not None and wants_refusal_notice(request_note)
                and REFUSAL_NOTICE not in body
            ):
                body = f"{body}\n\n{REFUSAL_NOTICE}"
            status = "present"
            if skip_rating:
                rating, status = None, "skipped"
            elif rating is None or narrator_mocks_ongoing(rating):
                mocked = rating is not None
                if mocked:
                    ongoing = "retried"
                status = "missing"
                again = await self._rating_only(
                    root, data, body, request_note, ongoing_retry=mocked,
                )
                if again is not None:
                    rating, status = again, "retried"
                elif mocked:
                    status = "present"
        text = body if rating is None else f"{body}\n\n{rating}"
        if narrator_mocks_ongoing(text):
            ongoing = "retried_left"
        return SummaryResult(text, self.runner.contract.model, len(included), status, ongoing)

    async def _rating_only(
        self, root: Path, data: bytes, body: str, note: str | None = None,
        *, ongoing_retry: bool = False,
    ) -> str | None:
        """Ask once for the closing rating alone; a bad or failed answer leaves it out."""
        summary = json.dumps({"type": "summary", "body": body}, ensure_ascii=False).encode()
        workspace = InputWorkspace.create(root, data.rstrip(b"\n") + b"\n" + summary + b"\n")
        try:
            answer = await self.runner.execute(workspace, rating_prompt(note, ongoing_retry=ongoing_retry))
        except CodexRunError:
            return None
        _rest, rating = split_rating(answer)
        if rating is None or narrator_uses_hate_term(rating):
            return None
        return rating
