"""Transaction-local recheck scheduling shared by Gateway edits and History workers."""

import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

import discord

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _us(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("Recheck timestamps must be timezone aware")
    delta = value.astimezone(UTC) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def reset_recheck(
    connection: sqlite3.Connection, guild_id: int, channel_id: int, *,
    now: datetime, retention_days: int, reason: str,
) -> bool:
    """Replace one channel's work with a full retained pass inside the caller's transaction.

    ``started_us`` is also a strictly advancing generation. During history, ``finished_us``
    stores the actual frozen upper boundary so same-tick generations never extend the range.
    Existing watch tokens, notification IDs and permission blocks are preserved.
    """
    if not 1 <= retention_days <= 30:
        raise ValueError("Retention must be between 1 and 30 days")
    end_us = _us(now)
    cutoff_us = _us(now - timedelta(days=retention_days))
    before_id = discord.utils.time_snowflake(now, high=True) + 1
    row = connection.execute(
        "SELECT b.started_us FROM backfill_state b JOIN watched_channels w "
        "ON b.guild_id=w.guild_id AND b.channel_id=w.channel_id "
        "WHERE b.guild_id=? AND b.channel_id=?", (guild_id, channel_id),
    ).fetchone()
    if row is None:
        watched = connection.execute(
            "SELECT 1 FROM watched_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        ).fetchone()
        if watched is None:
            return False
        connection.execute(
            "INSERT INTO backfill_state (guild_id, channel_id, token, first_watch, started_us, "
            "cutoff_us, before_id) VALUES (?, ?, ?, 0, ?, ?, ?)",
            (guild_id, channel_id, secrets.token_hex(16), end_us - 1, cutoff_us, before_id),
        )
        row = (end_us - 1,)
    generation = max(end_us, row[0] + 1)
    connection.execute(
        "DELETE FROM coverage_recheck WHERE guild_id=? AND channel_id=?",
        (guild_id, channel_id),
    )
    connection.execute(
        "INSERT INTO coverage_recheck (guild_id, channel_id, start_us, end_us, reason) "
        "VALUES (?, ?, ?, ?, ?)", (guild_id, channel_id, cutoff_us, end_us, reason),
    )
    connection.execute(
        "UPDATE backfill_state SET phase='history', started_us=?, cutoff_us=?, before_id=?, "
        "finished_us=?, overlap_start_us=NULL, overlap_before_id=NULL, verified_us=NULL, "
        "retry_at_us=0 WHERE guild_id=? AND channel_id=?",
        (generation, cutoff_us, before_id, end_us, guild_id, channel_id),
    )
    return True
