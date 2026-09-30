"""Summarize request-scoped message records through the pinned Codex CLI."""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Self

from yoyackbot.codex import CodexContract, CodexContractError, CodexFailure
from yoyackbot.codex_runner import CodexRunError, SandboxedCodex
from yoyackbot.config import Settings
from yoyackbot.domain import MessageRecord, SummaryMode, SummaryResult
from yoyackbot.input_files import InputWorkspace, serialize_conversation
from yoyackbot.output_quality import OutputIssue, inspect_output
from yoyackbot.summary_prompt import prompt_for


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
    ) -> SummaryResult:
        included = [item for item in messages if item.message_id != trigger_message_id]
        if not included:
            raise ValueError("Summary requires at least one eligible message")
        data = serialize_conversation(
            included, channel_name=channel_name, range_label=range_label,
            trigger_message_id=trigger_message_id, max_bytes=self.settings.max_input_bytes,
            on_size=on_input_size,
        )
        root = self.settings.input_directory.absolute()
        async with self._slots:
            workspace = InputWorkspace.create(root, data)
            result = await self.runner.execute(workspace, prompt_for(mode))
            source_bodies = [item.content for item in included]
            issue = inspect_output(result, source_bodies)
            if issue in (OutputIssue.SPEAKER_KEY, OutputIssue.HATE_TERM):
                retry_workspace = InputWorkspace.create(root, data)
                result = await self.runner.execute(retry_workspace, prompt_for(
                    mode, speaker_retry=issue is OutputIssue.SPEAKER_KEY,
                    hate_retry=issue is OutputIssue.HATE_TERM,
                ))
        if inspect_output(result, [item.content for item in included]) is not None:
            raise CodexRunError(CodexFailure.OUTPUT_INVALID)
        return SummaryResult(result, self.runner.contract.model, len(included))
