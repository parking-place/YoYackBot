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
from yoyackbot.input_files import InputWorkspace, message_keys, serialize_conversation
from yoyackbot.output_quality import (
    OutputIssue,
    inspect_output,
    name_underline,
    narrator_mocks_ongoing,
    rating_issue,
    split_rating,
    strip_emoji,
    summary_body_missing,
    topic_critique,
)
from yoyackbot.parser import wants_no_emoji, wants_no_rating, wants_refusal_notice
from yoyackbot.rating_pool import (
    filter_candidates,
    parse_candidates,
    parse_judgement,
    usable_rating,
)
from yoyackbot.speaker_names import speaker_labels
from yoyackbot.summary_prompt import (
    REFUSAL_NOTICE,
    prompt_for,
    rating_candidates_prompt,
    rating_judge_prompt,
)


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
        recent_ratings: Sequence[str] = (),
        tone: str | None = None,
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
                workspace, prompt_for(mode, note=request_note, skip_rating=skip_rating, tone=tone)
            )
            source_bodies = [item.content for item in included]
            keys = frozenset(message_keys(sorted(
                included, key=lambda item: (item.created_at, item.message_id),
            )).values())
            issue = summary_issue(result, source_bodies, keys)
            ongoing = "none"
            if issue in (
                OutputIssue.SPEAKER_KEY, OutputIssue.HATE_TERM, OutputIssue.NO_BODY,
                OutputIssue.MESSAGE_KEY,
            ):
                retry_workspace = InputWorkspace.create(root, data)
                result = await self.runner.execute(retry_workspace, prompt_for(
                    mode, note=request_note, skip_rating=skip_rating, tone=tone,
                    speaker_retry=issue is OutputIssue.SPEAKER_KEY,
                    hate_retry=issue is OutputIssue.HATE_TERM,
                    message_key_retry=issue is OutputIssue.MESSAGE_KEY,
                ))
            elif issue is None and narrator_mocks_ongoing(split_rating(result)[0]):
                ongoing = "retried"
                retry_workspace = InputWorkspace.create(root, data)
                retried = await self.runner.execute(retry_workspace, prompt_for(
                    mode, note=request_note, skip_rating=skip_rating, ongoing_retry=True, tone=tone,
                ))
                if summary_issue(retried, source_bodies, keys) is None:
                    result = retried
            body, rating = split_rating(result)
            if summary_issue(result, source_bodies, keys) is not None:
                # Only an unusable rating may be dropped; a bad body is never published.
                if rating is None or summary_issue(body, source_bodies, keys) is not None:
                    raise CodexRunError(CodexFailure.OUTPUT_INVALID)
                rating = None
            elif rating is not None and rating_issue(rating, source_bodies, keys) is not None:
                rating = None
            if (
                request_note is not None and wants_refusal_notice(request_note)
                and REFUSAL_NOTICE not in body
            ):
                body = f"{body}\n\n{REFUSAL_NOTICE}"
            names = [*speaker_labels(included).values(), *(item.author_name for item in included)]
            candidates = similar = 0
            if skip_rating:
                rating, status = None, "skipped"
            else:
                # The summary's own line is only a fallback; ten candidates and a judge pick it.
                own = rating if rating is not None and usable_rating(
                    rating, source_bodies, names, keys,
                ) else None
                rating, status, candidates, similar = await self._pick_rating(
                    root, data, body, source_bodies, names, keys, request_note,
                    recent_ratings, own, tone,
                )
        text = self._compose(body, rating, request_note)
        if inspect_output(text, source_bodies, keys) is not None:
            # The composed result passes the same checks; a rating that breaks it is left out.
            if rating is None:
                raise CodexRunError(CodexFailure.OUTPUT_INVALID)
            rating, status = None, "missing"
            text = self._compose(body, None, request_note)
            if inspect_output(text, source_bodies, keys) is not None:
                raise CodexRunError(CodexFailure.OUTPUT_INVALID)
        if narrator_mocks_ongoing(text):
            ongoing = "retried_left"
        posted = split_rating(text)[1] if rating is not None else None
        return SummaryResult(
            text, self.runner.contract.model, len(included), status, ongoing, topic_critique(text),
            name_underline(text, list(speaker_labels(included).values())),
            rating_text=posted, rating_candidates=candidates, rating_similar=similar,
        )

    @staticmethod
    def _compose(body: str, rating: str | None, note: str | None) -> str:
        text = body if rating is None else f"{body}\n\n{rating}"
        return strip_emoji(text) if note is not None and wants_no_emoji(note) else text

    async def _ask(self, root: Path, data: bytes, extra: Sequence[dict], prompt: str) -> str | None:
        """One auxiliary call over the conversation plus data lines; failures return None."""
        lines = b"".join(json.dumps(item, ensure_ascii=False).encode() + b"\n" for item in extra)
        workspace = InputWorkspace.create(root, data.rstrip(b"\n") + b"\n" + lines)
        try:
            return await self.runner.execute(workspace, prompt)
        except CodexRunError:
            return None

    async def _candidates(
        self, root: Path, data: bytes, context: Sequence[dict], source_bodies: Sequence[str],
        names: Sequence[str], keys: frozenset[str], note: str | None, *, regenerate: bool,
        tone: str | None = None,
    ) -> list[str] | None:
        answer = await self._ask(
            root, data, context, rating_candidates_prompt(note, regenerate=regenerate, tone=tone),
        )
        if answer is None:
            return None
        return filter_candidates(parse_candidates(answer), source_bodies, names, keys)

    async def _pick_rating(
        self, root: Path, data: bytes, body: str, source_bodies: Sequence[str],
        names: Sequence[str], keys: frozenset[str], note: str | None,
        recent: Sequence[str], own: str | None, tone: str | None = None,
    ) -> tuple[str | None, str, int, int]:
        """(rating, status, valid candidates, similar). At most three calls are added here."""
        context = [{"type": "summary", "body": body},
                   *({"type": "recent_rating", "text": item} for item in recent)]
        found = await self._candidates(
            root, data, context, source_bodies, names, keys, note, regenerate=False, tone=tone,
        )
        fallback = (own, "fallback_summary") if own is not None else (None, "missing")
        if found is None:
            return (*fallback, 0, 0)
        similar = 0
        if found:
            answer = await self._ask(root, data, [*context, *(
                {"type": "candidate", "number": index, "text": item}
                for index, item in enumerate(found, start=1)
            )], rating_judge_prompt(custom_tone=tone is not None))
            verdict = parse_judgement(answer, len(found)) if answer is not None else None
            if verdict is None:
                return found[0], "fallback_first", len(found), 0
            marked, chosen = verdict
            similar = len(marked)
            if chosen is not None:
                return found[chosen - 1], "picked", len(found), similar
            if similar < len(found):
                remaining = [item for index, item in enumerate(found, 1) if index not in marked]
                return remaining[0], "fallback_first", len(found), similar
        again = await self._candidates(
            root, data, context, source_bodies, names, keys, note, regenerate=True, tone=tone,
        )
        if again:
            return again[0], "regenerated", len(again), similar
        return (*fallback, len(found), similar)


def summary_issue(
    text: str, source_bodies: Sequence[str], keys: frozenset[str] = frozenset(),
) -> OutputIssue | None:
    """Core checks on the whole answer, then a real summary must remain beside the rating."""
    issue = inspect_output(text, source_bodies, keys)
    if issue is None and summary_body_missing(split_rating(text)[0], (REFUSAL_NOTICE,)):
        return OutputIssue.NO_BODY
    return issue
