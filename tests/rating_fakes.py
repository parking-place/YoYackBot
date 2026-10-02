"""Shared fake-runner helpers for the 1.3.0 rating candidates and judge calls."""

from yoyackbot.codex import CodexFailure
from yoyackbot.codex_runner import CodexRunError
from yoyackbot.summary_prompt import RATING_CANDIDATES_PROMPT, RATING_JUDGE_PROMPT

_HEADS = (RATING_CANDIDATES_PROMPT[:60], RATING_JUDGE_PROMPT[:60])


def is_rating_step(prompt: str) -> bool:
    """True for the candidate or judge call that follows a summary."""
    return prompt.startswith(_HEADS)


def is_candidates(prompt: str) -> bool:
    return prompt.startswith(RATING_CANDIDATES_PROMPT[:60])


def is_judge(prompt: str) -> bool:
    return prompt.startswith(RATING_JUDGE_PROMPT[:60])


def skip_rating_step(workspace, prompt: str) -> None:
    """Tests about other behaviour: the candidate call is unavailable, so the summary's own
    rating line is kept (`fallback_summary`) or none is posted (`missing`)."""
    if is_rating_step(prompt):
        workspace.close()
        raise CodexRunError(CodexFailure.PROCESS)


def candidates(*lines: str) -> str:
    return "\n".join(
        f"{index}. **요약창섭의 떡밥 한줄 평가** : {line}" for index, line in enumerate(lines, 1)
    )
