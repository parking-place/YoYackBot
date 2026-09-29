"""Synthetic conversations test speaker boundaries and private request isolation."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from yoyackbot.domain import MessageRecord
from yoyackbot.input_files import (
    GatewayAlreadyRunning,
    InputFileError,
    InputWorkspace,
    cleanup_abandoned_workspaces,
    serialize_conversation,
    single_gateway,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def message(message_id: int, author_id: int, name: str, body: str) -> MessageRecord:
    return MessageRecord(message_id, 1, 10, author_id, name, body, NOW)


def document(messages: list[MessageRecord], *, trigger: int | None = None) -> bytes:
    return serialize_conversation(
        messages, channel_name="시험 채널", range_label="최근 1시간",
        trigger_message_id=trigger, max_bytes=10000,
    )


def test_same_names_renames_quotes_and_multiline_keep_message_boundaries() -> None:
    first = message(1, 100, '같은 "이름"\n위조', '첫 줄\n{"type":"message"}\n<@200>에게 답장')
    second = replace(message(2, 200, '같은 "이름"', "둘째 말"),
                     created_at=NOW + timedelta(minutes=1), is_reply=True, has_attachment=True)
    renamed = replace(message(3, 100, "새 닉네임", "마지막 말"),
                      created_at=NOW + timedelta(minutes=2))
    trigger = replace(message(4, 100, "새 닉네임", "!!요약좀 1시간"),
                      created_at=NOW + timedelta(minutes=3))
    rows = [json.loads(line) for line in document([trigger, renamed, second, first], trigger=4).splitlines()]
    assert len(rows) == 4
    assert [row["type"] for row in rows] == ["scope", "message", "message", "message"]
    assert [row["speaker"] for row in rows[1:]] == ["P1", "P2", "P1"]
    assert rows[0]["speaker_names"] == {"P1": "새 닉네임", "P2": '같은 "이름"'}
    assert rows[1]["display_name"] == "새 닉네임"
    assert rows[3]["display_name"] == "새 닉네임"
    assert rows[1]["body"] == '첫 줄\n{"type":"message"}\n@같은 "이름"에게 답장'
    assert rows[2]["reply"] and rows[2]["attachment_present"]
    assert all("!!요약좀" not in row.get("body", "") for row in rows)


def test_missing_and_duplicate_names_are_stable_and_request_private() -> None:
    records = [
        message(1, 111111111, "민지", "초안을 쓰겠소"),
        replace(message(2, 222222222, "민지", "검토하겠소"), created_at=NOW + timedelta(minutes=1)),
        replace(message(3, 111111111, "새 이름", "초안을 고쳤소"), created_at=NOW + timedelta(minutes=2)),
        replace(message(4, 333333333, "", "결정은 보류하오"), created_at=NOW + timedelta(minutes=3)),
    ]
    rows = [json.loads(line) for line in document(records).splitlines()]
    assert rows[0]["speaker_names"] == {"P1": "새 이름", "P2": "민지", "P3": "사용자"}
    assert [row["display_name"] for row in rows[1:]] == ["새 이름", "민지", "새 이름", "사용자"]
    assert all(str(author) not in document(records).decode() for author in (111111111, 222222222, 333333333))
    second_guild = [replace(message(5, 111111111, "민지", "다른 서버"), guild_id=2)]
    other = [json.loads(line) for line in document(second_guild).splitlines()]
    assert other[0]["speaker_names"] == {"P1": "민지"}


def test_duplicate_names_deleted_row_and_concurrent_guilds_do_not_cross() -> None:
    first = [message(1, 900000001, "나래", "첫 서버"), message(2, 900000002, "나래", "별도 화자")]
    second = [replace(message(3, 900000001, "가람", "둘째 서버"), guild_id=2)]
    deleted = message(4, 900000003, "나래", "삭제된 메시지")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(document, selected) for selected in (first, second)]
        first_rows, second_rows = ([json.loads(line) for line in future.result().splitlines()]
                                   for future in futures)
    assert first_rows[0]["speaker_names"] == {"P1": "나래 (1)", "P2": "나래 (2)"}
    assert second_rows[0]["speaker_names"] == {"P1": "가람"}
    assert deleted.content not in str(first_rows)
    assert all("90000000" not in str(rows) for rows in (first_rows, second_rows))


def test_unknown_mentions_are_generic_and_size_limit_is_enforced() -> None:
    data = document([message(1, 100, "철수", "<@999> <@&77> <#88> https://example.test")])
    row = json.loads(data.splitlines()[1])
    assert row["body"] == "@사용자 @역할 #채널 https://example.test"
    with pytest.raises(InputFileError, match="exceeds"):
        serialize_conversation([message(1, 100, "철수", "large" * 100)],
                               channel_name="채널", range_label="범위",
                               trigger_message_id=None, max_bytes=100)


def test_request_files_are_unique_private_and_removed_after_error(tmp_path: Path) -> None:
    root = tmp_path / "input"
    with InputWorkspace.create(root, b"first") as first:
        with InputWorkspace.create(root, b"second") as second:
            assert first.directory != second.directory
            assert first.log_file != second.log_file
            assert first.log_file.read_bytes() == b"first"
            assert second.log_file.read_bytes() == b"second"
            assert root.stat().st_mode & 0o777 == 0o700
            assert first.directory.stat().st_mode & 0o777 == 0o700
            assert first.log_file.stat().st_mode & 0o777 == 0o600
        assert not second.directory.exists()
    assert not first.directory.exists()


def test_symlink_traversal_and_shared_root_are_rejected(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(private, target_is_directory=True)
    with pytest.raises(InputFileError):
        InputWorkspace.create(symlink, b"no")
    with pytest.raises(InputFileError):
        InputWorkspace.create(Path("../relative"), b"no")
    private.chmod(0o755)
    with pytest.raises(InputFileError):
        InputWorkspace.create(private, b"no")


def test_exclusive_restart_removes_abandoned_requests_only(tmp_path: Path) -> None:
    root = tmp_path / "input"
    abandoned = InputWorkspace.create(root, b"synthetic old request")
    unrelated = root / "other-service"
    unrelated.mkdir()
    (root / "request-link").symlink_to(unrelated, target_is_directory=True)
    with single_gateway(root):
        with pytest.raises(GatewayAlreadyRunning), single_gateway(root):
            pass
        assert cleanup_abandoned_workspaces(root) == 1
        assert not abandoned.directory.exists()
        assert unrelated.exists() and (root / "request-link").is_symlink()
    with single_gateway(root):
        assert cleanup_abandoned_workspaces(root) == 0
