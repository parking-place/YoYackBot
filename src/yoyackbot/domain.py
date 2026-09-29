"""Contracts shared by Discord, storage, model, and delivery layers."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from yoyackbot.scope import RangeScope


class SummaryMode(Enum):
    """Trusted prompt density; it never changes the collected range."""

    NORMAL = "normal"
    DETAILED = "detailed"
    SHORT = "short"


class RequestKind(Enum):
    TIME = "time"
    COUNT = "count"


@dataclass(frozen=True)
class MessageRecord:
    message_id: int
    guild_id: int
    channel_id: int
    author_id: int
    author_name: str
    content: str
    created_at: datetime
    edited_at: datetime | None = None
    cached_at: datetime | None = None
    has_attachment: bool = False
    is_reply: bool = False

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must have a timezone")
        if self.edited_at is not None and self.edited_at.tzinfo is None:
            raise ValueError("edited_at must have a timezone")
        if self.cached_at is not None and self.cached_at.tzinfo is None:
            raise ValueError("cached_at must have a timezone")


@dataclass(frozen=True)
class CoverageInterval:
    channel_id: int
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("coverage must be a nonempty aware time interval")


@dataclass(frozen=True)
class RangeRequest:
    kind: RequestKind
    accepted_at: datetime
    start: datetime | None = None
    count: int | None = None
    trigger_message_id: int | None = None

    def __post_init__(self) -> None:
        if self.accepted_at.tzinfo is None:
            raise ValueError("accepted_at must have a timezone")
        if self.kind is RequestKind.TIME:
            if self.start is None or self.start.tzinfo is None or self.start > self.accepted_at:
                raise ValueError("time requests need an aware start no later than accepted_at")
            if self.count is not None:
                raise ValueError("time requests cannot include count")
        elif self.kind is RequestKind.COUNT:
            if self.start is not None or self.count is None or self.count < 1:
                raise ValueError("count requests need a positive count and no start")


@dataclass(frozen=True)
class SummaryRequest:
    guild_id: int
    channel_id: int
    user_id: int
    requested_range: RangeRequest
    mode: SummaryMode = SummaryMode.NORMAL
    scope: "RangeScope | None" = None


@dataclass(frozen=True)
class SummaryResult:
    text: str
    model: str
    request_message_count: int


@dataclass(frozen=True)
class PublicationReceipt:
    message_ids: tuple[int, ...]
    last_success_at: datetime

    def __post_init__(self) -> None:
        if not self.message_ids or self.last_success_at.tzinfo is None:
            raise ValueError("Successful publication needs message IDs and an aware time")


class MessageStore(Protocol):
    def recent(
        self, guild_id: int, channel_id: int, start: datetime, end: datetime
    ) -> Sequence[MessageRecord]: ...


class SummaryEngine(Protocol):
    async def summarize(self, messages: Sequence[MessageRecord]) -> SummaryResult: ...


class SummaryPublisher(Protocol):
    async def publish(
        self, request: SummaryRequest, result: SummaryResult,
        selected: Sequence[MessageRecord],
    ) -> PublicationReceipt: ...
