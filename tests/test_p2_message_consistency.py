"""P2 cache retention, event ordering, and bounded History reconciliation regressions."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from yoyackbot.domain import CoverageInterval, MessageRecord
from yoyackbot.message_store import MessageStoreError, SQLiteMessageStore, _microseconds
from yoyackbot.watch_store import SQLiteWatchStore

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def message(message_id=100, **changes):
    return replace(
        MessageRecord(message_id, 1, 99, 3, "합성 화자", "기존 본문", NOW - timedelta(hours=1)),
        **changes,
    )


def setup_store(tmp_path, *, retention_days=30, clock=lambda: NOW):
    path = tmp_path / "cache.db"
    watches = SQLiteWatchStore(path)
    watches.replace(1, frozenset({99}))
    return SQLiteMessageStore(path, retention_days=retention_days, clock=clock)


def rows(store):
    with sqlite3.connect(store.path) as connection:
        return connection.execute(
            "SELECT message_id, content, edited_at_us, cached_at_us FROM messages "
            "ORDER BY message_id"
        ).fetchall()


def reconcile(store, records, boundary, *, lower_id=0, before_id=1000, cutoff=None):
    with store._connection() as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        return store._reconcile_page(
            connection, 1, 99, records, lower_id=lower_id, before_id=before_id,
            start_us=_microseconds(NOW - timedelta(days=30)), end_us=_microseconds(NOW),
            fetched_after_us=boundary, cached_at=NOW,
            cutoff_us=_microseconds(cutoff or NOW - timedelta(days=store.retention_days)),
        )


@pytest.mark.parametrize("days", [1, 7, 30])
@pytest.mark.parametrize("watched", [False, True])
def test_writes_enforce_current_retention_before_exact_and_after_cutoff(tmp_path, days, watched):
    store = setup_store(tmp_path, retention_days=days)
    cutoff = NOW - timedelta(days=days)
    for index, delta in enumerate((-1, 0, 1), start=100):
        record = message(index, created_at=cutoff + timedelta(microseconds=delta))
        if watched:
            assert store.upsert_if_watched(record, expected_version=1, cached_at=NOW) is (delta >= 0)
        else:
            store.upsert(record, cached_at=NOW)
    assert [row[0] for row in rows(store)] == [101, 102]


@pytest.mark.parametrize("days", [1, 7, 30])
def test_old_raw_and_cached_edits_cannot_restore_expired_messages(tmp_path, days):
    current = [NOW - timedelta(hours=1)]
    store = setup_store(tmp_path, retention_days=days, clock=lambda: current[0])
    record = message(created_at=NOW - timedelta(days=days, microseconds=1))
    store.upsert(record, cached_at=current[0])
    original = rows(store)
    current[0] = NOW
    assert not store.update_content(1, 99, 100, "늦은 수정", edited_at=NOW, cached_at=NOW)
    assert not store.update_content(1, 99, 100, "모호한 수정", edited_at=None, cached_at=NOW)
    assert rows(store) == original
    assert store.recheck(1, 99) == []
    assert store.prune_before(NOW - timedelta(days=days)) == 1
    assert not store.upsert_if_watched(
        replace(record, edited_at=NOW, content="늦은 수정"), expected_version=1, cached_at=NOW,
    )
    store.upsert(record, cached_at=current[0])
    assert rows(store) == []


def test_retention_is_rechecked_after_waiting_for_the_writer_lock(tmp_path, monkeypatch):
    current = [NOW]
    store = setup_store(tmp_path, retention_days=1, clock=lambda: current[0])
    waiting = Event()
    original_connection = store._connection

    @contextmanager
    def traced_connection():
        with original_connection() as connection:
            connection.set_trace_callback(
                lambda sql: waiting.set() if sql == "BEGIN IMMEDIATE" else None
            )
            yield connection

    monkeypatch.setattr(store, "_connection", traced_connection)
    with sqlite3.connect(store.path) as lock, ThreadPoolExecutor(max_workers=1) as executor:
        lock.execute("BEGIN IMMEDIATE")
        future = executor.submit(store.upsert, message(), cached_at=NOW)
        try:
            assert waiting.wait(timeout=2)
            current[0] = NOW + timedelta(days=2)
        finally:
            lock.commit()
        future.result(timeout=5)
    assert rows(store) == []


def test_shorter_retention_filters_reads_before_periodic_cleanup(tmp_path):
    store = setup_store(tmp_path)
    record = message(created_at=NOW - timedelta(days=2))
    store.upsert(record, cached_at=NOW)
    store.retention_days = 1
    assert len(rows(store)) == 1  # Read filtering must not rely on the periodic deletion.
    assert store.recent(1, 99, NOW - timedelta(days=30), NOW) == []
    assert store.latest(1, 99, NOW - timedelta(days=30), NOW, 100) == []


@pytest.mark.parametrize("order", [(1, 2), (2, 1)])
def test_raw_edit_order_and_equal_timestamp_conflicts_keep_the_newest_content(tmp_path, order):
    store = setup_store(tmp_path)
    store.upsert(message(), cached_at=NOW)
    for revision in order:
        store.update_content(
            1, 99, 100, f"본문 {revision}", edited_at=NOW + timedelta(seconds=revision), cached_at=NOW,
        )
    newest = rows(store)
    assert newest[0][1:3] == ("본문 2", _microseconds(NOW + timedelta(seconds=2)))
    assert not store.update_content(
        1, 99, 100, "같은 시각의 다른 본문", edited_at=NOW + timedelta(seconds=2), cached_at=NOW,
    )
    assert rows(store) == newest
    assert store.recheck(1, 99) == []


def test_cached_history_and_raw_edit_orders_share_the_monotonic_revision_policy(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(), cached_at=NOW)
    newest = message(content="최신 본문", edited_at=NOW + timedelta(seconds=2))
    assert store.upsert_if_watched(newest, expected_version=1, cached_at=NOW)
    for old in (
        message(content="과거 본문", edited_at=NOW + timedelta(seconds=1)),
        message(content="동시각 충돌", edited_at=newest.edited_at),
    ):
        store.upsert(old, cached_at=NOW)
    assert rows(store)[0][1:3] == ("최신 본문", _microseconds(newest.edited_at))
    assert not store.update_content(
        1, 99, 100, "과거 raw", edited_at=NOW + timedelta(seconds=1), cached_at=NOW,
    )
    assert store.delete_many(1, 99, {100}) == 1
    assert not store.update_content(1, 99, 100, "삭제 뒤 수정", edited_at=NOW, cached_at=NOW)
    store.upsert(newest, cached_at=NOW)
    assert rows(store) == []


@pytest.mark.parametrize("legacy", [False, True])
def test_unknown_timestamp_keeps_content_and_invalidates_active_generation(tmp_path, legacy):
    store = setup_store(tmp_path)
    store.upsert(message(), cached_at=NOW)
    with sqlite3.connect(store.path) as connection:
        if legacy:
            connection.execute("DELETE FROM backfill_state")
        before = connection.execute("SELECT started_us FROM backfill_state").fetchone()
    old_observed = rows(store)[0][3]
    for _ in range(2):
        assert not store.update_content(1, 99, 100, "확인되지 않은 본문", edited_at=None, cached_at=NOW)
    assert rows(store)[0][1:3] == ("기존 본문", None)
    assert rows(store)[0][3] > old_observed
    assert store.recheck(1, 99) == [CoverageInterval(99, NOW - timedelta(days=30), NOW)]
    with sqlite3.connect(store.path) as connection:
        generation, phase, first_watch = connection.execute(
            "SELECT started_us, phase, first_watch FROM backfill_state"
        ).fetchone()
        assert phase == "history"
        if before is not None:
            assert generation > before[0]
        if legacy:
            assert first_watch == 0


def test_unknown_timestamp_does_not_schedule_unknown_or_unwatched_message(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(101, channel_id=98), cached_at=NOW)
    assert not store.update_content(1, 99, 999, "모르는 본문", edited_at=None, cached_at=NOW)
    assert not store.update_content(1, 98, 101, "주시하지 않는 본문", edited_at=None, cached_at=NOW)
    assert not store.update_content(1, 98, 101, "주시하지 않는 수정", edited_at=NOW, cached_at=NOW)
    assert store.recheck(1, 99) == store.recheck(1, 98) == []
    assert rows(store)[0][1:3] == ("기존 본문", None)


def test_edit_timestamp_before_message_creation_cannot_replace_original_content(tmp_path):
    store = setup_store(tmp_path)
    original = message()
    store.upsert(original, cached_at=NOW)
    invalid_time = original.created_at - timedelta(microseconds=1)
    store.upsert(replace(original, content="잘못된 시각", edited_at=invalid_time), cached_at=NOW)
    assert not store.update_content(1, 99, 100, "잘못된 raw 시각", edited_at=invalid_time, cached_at=NOW)
    assert rows(store)[0][1:3] == ("기존 본문", None)


def test_cached_edit_without_timestamp_keeps_content_and_requests_recheck(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(), cached_at=NOW)
    assert not store.upsert_if_watched(
        message(content="시각 없는 cached 수정"), expected_version=1, cached_at=NOW,
    )
    assert rows(store)[0][1] == "기존 본문"
    assert store.recheck(1, 99)


def test_unknown_recheck_failure_rolls_back_observation_and_pending_changes(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(), cached_at=NOW)
    original = rows(store)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_recheck BEFORE UPDATE ON backfill_state "
            "BEGIN SELECT RAISE(ABORT, 'synthetic reset failure'); END"
        )
    with pytest.raises(MessageStoreError, match="Message edit failed"):
        store.update_content(1, 99, 100, "모호한 본문", edited_at=None, cached_at=NOW)
    assert rows(store) == original
    assert store.recheck(1, 99) == []


def test_legacy_recheck_mark_also_invalidates_an_active_generation(tmp_path):
    store = setup_store(tmp_path)
    with sqlite3.connect(store.path) as connection:
        before = connection.execute("SELECT started_us FROM backfill_state").fetchone()[0]
    start = NOW - timedelta(hours=1)
    assert store.mark_all_watched_recheck(start, NOW, reason="startup") == 1
    assert store.recheck(1, 99) == [CoverageInterval(99, start, NOW)]
    with sqlite3.connect(store.path) as connection:
        after = connection.execute("SELECT started_us FROM backfill_state").fetchone()[0]
    assert after > before


def test_completed_page_repairs_offline_edits_and_complete_empty_page_deletes(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(), cached_at=NOW)
    assert reconcile(
        store, [message(content="오프라인 수정", edited_at=NOW - timedelta(minutes=1))],
        store.history_boundary(1, 99, at=NOW),
    ) == 0
    assert rows(store)[0][1] == "오프라인 수정"
    assert reconcile(store, [], store.history_boundary(1, 99, at=NOW)) == 1
    assert rows(store) == []


@pytest.mark.parametrize("history_contains_live_message", [False, True])
def test_history_cannot_delete_or_overwrite_live_edits_or_resurrect_tombstones(
    tmp_path, history_contains_live_message,
):
    store = setup_store(tmp_path)
    store.upsert(message(100), cached_at=NOW)
    store.upsert(message(101), cached_at=NOW)
    boundary = store.history_boundary(1, 99, at=NOW)
    assert store.update_content(1, 99, 100, "실시간 최신 본문", edited_at=NOW, cached_at=NOW)
    assert store.delete_many(1, 99, {101}) == 1
    page = [message(101)]
    if history_contains_live_message:
        page.append(message(100))
    reconcile(store, page, boundary)
    assert [(row[0], row[1]) for row in rows(store)] == [(100, "실시간 최신 본문")]


def test_observation_watermark_survives_deletion_of_the_latest_row(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(100), cached_at=NOW)
    for _ in range(5):
        store.upsert(message(101), cached_at=NOW)
    boundary = store.history_boundary(1, 99, at=NOW)
    assert store.delete_many(1, 99, {101}) == 1
    assert store.update_content(1, 99, 100, "삭제 뒤 최신 본문", edited_at=NOW, cached_at=NOW)
    assert rows(store)[0][3] >= boundary
    assert reconcile(store, [], boundary) == 0
    assert rows(store)[0][1] == "삭제 뒤 최신 본문"
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM cache_observation_clock").fetchone()[0] == 1


def test_page_snowflake_boundaries_preserve_unread_messages_at_the_same_timestamp(tmp_path):
    store = setup_store(tmp_path)
    for message_id in (200, 201, 202):
        store.upsert(message(message_id), cached_at=NOW)
    boundary = store.history_boundary(1, 99, at=NOW)
    assert reconcile(store, [message(202)], boundary, lower_id=202, before_id=203) == 0
    assert [row[0] for row in rows(store)] == [200, 201, 202]
    boundary = store.history_boundary(1, 99, at=NOW)
    assert reconcile(store, [message(200)], boundary, lower_id=200, before_id=202) == 1
    assert [row[0] for row in rows(store)] == [200, 202]


def test_reconciliation_rechecks_retention_when_a_page_arrives(tmp_path):
    store = setup_store(tmp_path, retention_days=1)
    cutoff = NOW - timedelta(days=1)
    page = [
        message(100, created_at=cutoff - timedelta(microseconds=1)),
        message(101, created_at=cutoff),
        message(102, created_at=cutoff + timedelta(microseconds=1)),
    ]
    reconcile(store, page, store.history_boundary(1, 99, at=NOW), cutoff=cutoff)
    assert [row[0] for row in rows(store)] == [101, 102]


def test_page_insert_failure_rolls_back_missing_row_deletion_and_observation_clock(tmp_path):
    store = setup_store(tmp_path)
    store.upsert(message(100), cached_at=NOW)
    boundary = store.history_boundary(1, 99, at=NOW)
    original = rows(store)
    with sqlite3.connect(store.path) as connection:
        watermark = connection.execute("SELECT last_us FROM cache_observation_clock").fetchone()
        connection.execute(
            "CREATE TRIGGER fail_page BEFORE INSERT ON messages WHEN NEW.message_id=999 "
            "BEGIN SELECT RAISE(ABORT, 'synthetic page failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="synthetic page failure"):
        reconcile(store, [message(999)], boundary)
    assert rows(store) == original
    with sqlite3.connect(store.path) as connection:
        assert connection.execute("SELECT last_us FROM cache_observation_clock").fetchone() == watermark


def test_legacy_full_history_completion_also_filters_expired_incoming_records(tmp_path):
    store = setup_store(tmp_path, retention_days=1)
    request = CoverageInterval(99, NOW - timedelta(days=7), NOW)
    assert store.commit_history_complete(
        1, request, [message(created_at=NOW - timedelta(days=2))], exhausted=True,
        expected_version=1, verified_at=NOW,
    )
    assert rows(store) == []
    assert store.coverage(1, 99) == [CoverageInterval(99, NOW - timedelta(days=1), NOW)]
