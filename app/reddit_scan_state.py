"""Persistent scheduling and rate-limit state for Reddit RSS scans."""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
import random
import sqlite3
import time

from app.config import get_settings
from app.db import get_db


TIERS = {"high", "standard", "research"}


@dataclass(frozen=True)
class FeedTask:
    id: int
    campaign_key: str
    feed_url: str
    keyword: str
    subreddit: str
    tier: str
    next_due_at: float


@dataclass(frozen=True)
class CooldownState:
    cooldown_until: float
    strike_count: int
    last_429_at: float | None
    retry_after_seconds: float | None

    def remaining_seconds(self, now: float | None = None) -> int:
        current = time.time() if now is None else now
        return max(0, int(self.cooldown_until - current))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_scan_state_schema() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reddit_feed_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_key TEXT NOT NULL,
                feed_url TEXT NOT NULL,
                keyword TEXT NOT NULL,
                subreddit TEXT NOT NULL,
                tier TEXT NOT NULL,
                next_due_at REAL NOT NULL DEFAULT 0,
                last_attempt_at REAL,
                last_success_at REAL,
                last_status TEXT NOT NULL DEFAULT 'pending',
                consecutive_errors INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(campaign_key, feed_url)
            );

            CREATE INDEX IF NOT EXISTS idx_reddit_feed_schedule_due
            ON reddit_feed_schedule(next_due_at, campaign_key);

            CREATE TABLE IF NOT EXISTS reddit_rate_limit_state (
                service TEXT PRIMARY KEY,
                cooldown_until REAL NOT NULL DEFAULT 0,
                strike_count INTEGER NOT NULL DEFAULT 0,
                last_429_at REAL,
                retry_after_seconds REAL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """INSERT OR IGNORE INTO reddit_rate_limit_state (
                   service, cooldown_until, strike_count, last_429_at,
                   retry_after_seconds, updated_at
               ) VALUES ('reddit_rss', 0, 0, NULL, NULL, ?)""",
            (_utc_now(),),
        )


def sync_campaign_feeds(campaign_key: str, feeds: list[dict]) -> None:
    """Upsert the current feed set and remove stale URLs for one campaign."""
    ensure_scan_state_schema()
    now_text = _utc_now()
    urls: list[str] = []
    with get_db() as conn:
        for feed in feeds:
            tier = str(feed["tier"])
            if tier not in TIERS:
                raise ValueError(f"Unknown Reddit feed tier: {tier}")
            url = str(feed["feed_url"])
            urls.append(url)
            conn.execute(
                """INSERT INTO reddit_feed_schedule (
                       campaign_key, feed_url, keyword, subreddit, tier,
                       next_due_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                   ON CONFLICT(campaign_key, feed_url) DO UPDATE SET
                       keyword = excluded.keyword,
                       subreddit = excluded.subreddit,
                       tier = excluded.tier,
                       updated_at = excluded.updated_at""",
                (
                    campaign_key,
                    url,
                    str(feed["keyword"]),
                    str(feed["subreddit"]),
                    tier,
                    now_text,
                    now_text,
                ),
            )
        if urls:
            placeholders = ",".join("?" for _ in urls)
            conn.execute(
                f"""DELETE FROM reddit_feed_schedule
                    WHERE campaign_key = ? AND feed_url NOT IN ({placeholders})""",
                [campaign_key, *urls],
            )
        else:
            conn.execute(
                "DELETE FROM reddit_feed_schedule WHERE campaign_key = ?",
                (campaign_key,),
            )


def select_feed_tasks(
    campaign_keys: list[str],
    limit: int,
    *,
    force: bool = False,
    now: float | None = None,
) -> list[FeedTask]:
    """Return due feeds in round-robin campaign order without mutating them."""
    ensure_scan_state_schema()
    if limit <= 0 or not campaign_keys:
        return []
    current = time.time() if now is None else now
    if get_cooldown_state().remaining_seconds(current) > 0:
        return []
    placeholders = ",".join("?" for _ in campaign_keys)
    due_clause = "" if force else "AND next_due_at <= ?"
    params: list[object] = [*campaign_keys]
    if not force:
        params.append(current)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM reddit_feed_schedule
                WHERE campaign_key IN ({placeholders}) {due_clause}
                ORDER BY next_due_at ASC,
                         COALESCE(last_attempt_at, 0) ASC,
                         id ASC""",
            params,
        ).fetchall()

    grouped: OrderedDict[str, deque[sqlite3.Row]] = OrderedDict()
    for row in rows:
        grouped.setdefault(row["campaign_key"], deque()).append(row)

    selected: list[FeedTask] = []
    while grouped and len(selected) < limit:
        for campaign_key in list(grouped):
            queue = grouped[campaign_key]
            row = queue.popleft()
            selected.append(_task_from_row(row))
            if not queue:
                del grouped[campaign_key]
            if len(selected) >= limit:
                break
    return selected


def _task_from_row(row: sqlite3.Row) -> FeedTask:
    return FeedTask(
        id=int(row["id"]),
        campaign_key=str(row["campaign_key"]),
        feed_url=str(row["feed_url"]),
        keyword=str(row["keyword"]),
        subreddit=str(row["subreddit"]),
        tier=str(row["tier"]),
        next_due_at=float(row["next_due_at"]),
    )


def mark_feed_attempt(task_id: int, *, now: float | None = None) -> None:
    current = time.time() if now is None else now
    with get_db() as conn:
        conn.execute(
            """UPDATE reddit_feed_schedule
               SET last_attempt_at = ?, last_status = 'fetching', updated_at = ?
               WHERE id = ?""",
            (current, _utc_now(), task_id),
        )


def mark_feed_success(
    task_id: int,
    tier: str,
    *,
    now: float | None = None,
    interval_minutes: float | None = None,
) -> None:
    current = time.time() if now is None else now
    interval = _tier_interval_minutes(tier) if interval_minutes is None else interval_minutes
    with get_db() as conn:
        conn.execute(
            """UPDATE reddit_feed_schedule
               SET last_success_at = ?, next_due_at = ?, last_status = 'ok',
                   consecutive_errors = 0, updated_at = ?
               WHERE id = ?""",
            (current, current + max(0, interval) * 60, _utc_now(), task_id),
        )


def mark_feed_error(
    task_id: int,
    status: str,
    *,
    retry_at: float | None = None,
    now: float | None = None,
) -> None:
    current = time.time() if now is None else now
    next_due = retry_at if retry_at is not None else current + 30 * 60
    with get_db() as conn:
        conn.execute(
            """UPDATE reddit_feed_schedule
               SET next_due_at = ?, last_status = ?,
                   consecutive_errors = consecutive_errors + 1, updated_at = ?
               WHERE id = ?""",
            (next_due, status, _utc_now(), task_id),
        )


def _tier_interval_minutes(tier: str) -> float:
    settings = get_settings()
    if tier == "high":
        low = settings.reddit_high_intent_interval_min_minutes
        high = settings.reddit_high_intent_interval_max_minutes
    elif tier == "research":
        low = settings.reddit_research_interval_min_minutes
        high = settings.reddit_research_interval_max_minutes
    else:
        low = settings.reddit_standard_interval_min_minutes
        high = settings.reddit_standard_interval_max_minutes
    low, high = sorted((max(1, low), max(1, high)))
    return random.uniform(low, high)


def get_cooldown_state() -> CooldownState:
    ensure_scan_state_schema()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM reddit_rate_limit_state WHERE service = 'reddit_rss'"
        ).fetchone()
    return CooldownState(
        cooldown_until=float(row["cooldown_until"] or 0),
        strike_count=int(row["strike_count"] or 0),
        last_429_at=float(row["last_429_at"]) if row["last_429_at"] is not None else None,
        retry_after_seconds=(
            float(row["retry_after_seconds"])
            if row["retry_after_seconds"] is not None
            else None
        ),
    )


def record_rate_limit(
    retry_after_seconds: float | None,
    *,
    now: float | None = None,
) -> CooldownState:
    """Persist an immediate global pause, escalating 2h, 4h, 8h, then 12h."""
    ensure_scan_state_schema()
    current = time.time() if now is None else now
    previous = get_cooldown_state()
    consecutive_window = get_settings().reddit_429_strike_window_hours * 60 * 60
    if previous.last_429_at is None or current - previous.last_429_at > consecutive_window:
        strikes = 1
    else:
        strikes = previous.strike_count + 1

    if retry_after_seconds is not None:
        cooldown_seconds = max(0.0, retry_after_seconds)
    else:
        steps = get_settings().reddit_429_cooldown_steps
        cooldown_minutes = steps[min(strikes - 1, len(steps) - 1)]
        cooldown_seconds = cooldown_minutes * 60
    cooldown_until = current + cooldown_seconds
    with get_db() as conn:
        conn.execute(
            """UPDATE reddit_rate_limit_state
               SET cooldown_until = ?, strike_count = ?, last_429_at = ?,
                   retry_after_seconds = ?, updated_at = ?
               WHERE service = 'reddit_rss'""",
            (
                cooldown_until,
                strikes,
                current,
                retry_after_seconds,
                _utc_now(),
            ),
        )
    return get_cooldown_state()


def record_recovery(*, now: float | None = None) -> None:
    """Clear strike history only after the configured quiet window has elapsed.

    A single successful request immediately after cooldown must not erase the
    previous 429. Otherwise a later URL in the same scan would repeatedly get
    the shortest two-hour pause instead of escalating to four, eight, and
    twelve hours.
    """
    current = time.time() if now is None else now
    state = get_cooldown_state()
    strike_window = get_settings().reddit_429_strike_window_hours * 60 * 60
    if (
        state.strike_count <= 0
        or state.last_429_at is None
        or current - state.last_429_at <= strike_window
    ):
        return
    with get_db() as conn:
        conn.execute(
            """UPDATE reddit_rate_limit_state
               SET cooldown_until = 0, strike_count = 0, last_429_at = NULL,
                   retry_after_seconds = NULL, updated_at = ?
               WHERE service = 'reddit_rss'""",
            (_utc_now(),),
        )


def reset_rate_limit_state() -> None:
    ensure_scan_state_schema()
    with get_db() as conn:
        conn.execute(
            """UPDATE reddit_rate_limit_state
               SET cooldown_until = 0, strike_count = 0, last_429_at = NULL,
                   retry_after_seconds = NULL, updated_at = ?
               WHERE service = 'reddit_rss'""",
            (_utc_now(),),
        )


def list_feed_schedule(campaign_key: str | None = None) -> list[sqlite3.Row]:
    """Small read API for diagnostics and tests."""
    ensure_scan_state_schema()
    with get_db() as conn:
        if campaign_key:
            return conn.execute(
                """SELECT * FROM reddit_feed_schedule
                   WHERE campaign_key = ? ORDER BY next_due_at, id""",
                (campaign_key,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM reddit_feed_schedule ORDER BY next_due_at, id"
        ).fetchall()
