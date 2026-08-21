import sqlite3
from pathlib import Path
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from app.config import get_settings
from app.campaign import campaign_key_for_path


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                reddit_id TEXT PRIMARY KEY,
                source_reddit_id TEXT,
                campaign_key TEXT NOT NULL DEFAULT 'default',
                title TEXT NOT NULL,
                subreddit TEXT NOT NULL,
                permalink TEXT NOT NULL,
                url TEXT NOT NULL,
                author TEXT,
                selftext TEXT,
                query TEXT,
                created_utc REAL,
                first_seen_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'seen'
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reddit_id TEXT NOT NULL,
                intent_score REAL NOT NULL,
                reason TEXT NOT NULL,
                comment_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                response_type TEXT DEFAULT 'helpful_only',
                should_reply INTEGER DEFAULT 1,
                should_mention_brand INTEGER DEFAULT 0,
                should_include_link INTEGER DEFAULT 0,
                strategy_reason TEXT,
                generated_draft TEXT,
                relevance_score REAL DEFAULT 0,
                purchase_intent_score REAL DEFAULT 0,
                product_fit_score REAL DEFAULT 0,
                urgency_score REAL DEFAULT 0,
                reachability_score REAL DEFAULT 0,
                promotion_risk_score REAL DEFAULT 0,
                market_fit_score REAL DEFAULT 0,
                positive_signals TEXT DEFAULT '[]',
                negative_signals TEXT DEFAULT '[]',
                feedback_reason TEXT,
                final_comment TEXT,
                campaign_key TEXT NOT NULL DEFAULT 'default',
                assignee TEXT,
                review_notes TEXT,
                outcome TEXT NOT NULL DEFAULT 'none',
                conversion_value REAL,
                slack_notified_at TEXT,
                email_notified_at TEXT,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                FOREIGN KEY (reddit_id) REFERENCES posts(reddit_id)
            );
            """
        )
        _add_column_if_missing(conn, "posts", "query", "TEXT")
        _add_column_if_missing(conn, "posts", "source_reddit_id", "TEXT")
        _add_column_if_missing(conn, "posts", "campaign_key", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing(conn, "drafts", "response_type", "TEXT DEFAULT 'helpful_only'")
        _add_column_if_missing(conn, "drafts", "should_reply", "INTEGER DEFAULT 1")
        _add_column_if_missing(conn, "drafts", "should_mention_brand", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "drafts", "should_include_link", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "drafts", "strategy_reason", "TEXT")
        _add_column_if_missing(conn, "drafts", "generated_draft", "TEXT")
        _add_column_if_missing(conn, "drafts", "slack_notified_at", "TEXT")
        _add_column_if_missing(conn, "drafts", "email_notified_at", "TEXT")
        for column in [
            "relevance_score", "purchase_intent_score", "product_fit_score",
            "urgency_score", "reachability_score", "promotion_risk_score",
            "market_fit_score",
        ]:
            _add_column_if_missing(conn, "drafts", column, "REAL DEFAULT 0")
        _add_column_if_missing(conn, "drafts", "positive_signals", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "drafts", "negative_signals", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "drafts", "feedback_reason", "TEXT")
        _add_column_if_missing(conn, "drafts", "final_comment", "TEXT")
        _add_column_if_missing(conn, "drafts", "campaign_key", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing(conn, "drafts", "assignee", "TEXT")
        _add_column_if_missing(conn, "drafts", "review_notes", "TEXT")
        _add_column_if_missing(conn, "drafts", "outcome", "TEXT NOT NULL DEFAULT 'none'")
        _add_column_if_missing(conn, "drafts", "conversion_value", "REAL")

        # V0.1 rows predate campaign attribution. Attribute them to the active file.
        active_key = campaign_key_for_path(
            getattr(get_settings(), "campaign_path", "campaigns/campaign.yaml")
        )
        conn.execute(
            "UPDATE posts SET source_reddit_id = reddit_id WHERE source_reddit_id IS NULL"
        )
        conn.execute(
            "UPDATE posts SET campaign_key = ? WHERE campaign_key = 'default'",
            (active_key,),
        )
        conn.execute(
            """UPDATE drafts SET campaign_key = COALESCE(
                   (SELECT posts.campaign_key FROM posts WHERE posts.reddit_id = drafts.reddit_id),
                   ?
               ) WHERE campaign_key = 'default'""",
            (active_key,),
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_campaign_source "
            "ON posts(campaign_key, source_reddit_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_drafts_campaign_status "
            "ON drafts(campaign_key, status, created_at)"
        )


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    database_path = Path(get_settings().database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _storage_reddit_id(reddit_id: str, campaign_key: str) -> str:
    return f"{campaign_key}:{reddit_id}"


def has_seen_post(reddit_id: str, campaign_key: str = "default") -> bool:
    with get_db() as conn:
        row = conn.execute(
            """SELECT 1 FROM posts
               WHERE campaign_key = ? AND source_reddit_id = ? LIMIT 1""",
            (campaign_key, reddit_id),
        ).fetchone()
        return row is not None


def save_post(post: dict, campaign_key: str = "default") -> None:
    source_reddit_id = post["reddit_id"]
    storage_reddit_id = _storage_reddit_id(source_reddit_id, campaign_key)
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO posts (
                reddit_id, source_reddit_id, campaign_key, title, subreddit,
                permalink, url, author, selftext, query, created_utc,
                first_seen_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'seen')
            """,
            (
                storage_reddit_id,
                source_reddit_id,
                campaign_key,
                post["title"],
                post["subreddit"],
                post["permalink"],
                post["url"],
                post.get("author"),
                post.get("selftext", ""),
                post.get("query"),
                post.get("created_utc"),
                utc_now(),
            ),
        )


def save_draft(
    reddit_id: str,
    intent_score: float,
    reason: str,
    comment_text: str,
    response_type: str = "helpful_only",
    should_reply: bool = True,
    should_mention_brand: bool = False,
    should_include_link: bool = False,
    strategy_reason: str = "",
    qualification: dict | None = None,
    campaign_key: str = "default",
    status: str = "new",
) -> int:
    import json
    qualification = qualification or {}
    storage_reddit_id = _storage_reddit_id(reddit_id, campaign_key)
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO drafts (
                reddit_id, intent_score, reason, comment_text, status,
                response_type, should_reply, should_mention_brand,
                should_include_link, strategy_reason, generated_draft,
                relevance_score, purchase_intent_score, product_fit_score,
                urgency_score, reachability_score, promotion_risk_score,
                market_fit_score, positive_signals, negative_signals,
                campaign_key, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                storage_reddit_id,
                intent_score,
                reason,
                comment_text,
                status,
                response_type,
                int(should_reply),
                int(should_mention_brand),
                int(should_include_link),
                strategy_reason,
                comment_text,
                float(qualification.get("relevance_score") or 0),
                float(qualification.get("purchase_intent_score") or 0),
                float(qualification.get("product_fit_score") or 0),
                float(qualification.get("urgency_score") or 0),
                float(qualification.get("reachability_score") or 0),
                float(qualification.get("promotion_risk_score") or 0),
                float(qualification.get("market_fit_score") or 0),
                json.dumps(qualification.get("positive_signals", [])),
                json.dumps(qualification.get("negative_signals", [])),
                campaign_key,
                utc_now(),
            ),
        )
        conn.execute(
            "UPDATE posts SET status = 'drafted' WHERE reddit_id = ?",
            (storage_reddit_id,),
        )
        return int(cursor.lastrowid)


def get_draft(draft_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT drafts.*, posts.source_reddit_id AS source_reddit_id,
                   posts.title, posts.permalink, posts.subreddit, posts.query,
                   posts.selftext, posts.author
            FROM drafts
            JOIN posts ON posts.reddit_id = drafts.reddit_id
            WHERE drafts.id = ?
            """,
            (draft_id,),
        ).fetchone()


def mark_draft_status(
    draft_id: int,
    status: str,
    feedback_reason: str | None = None,
    final_comment: str | None = None,
    assignee: str | None = None,
    review_notes: str | None = None,
    outcome: str | None = None,
    conversion_value: float | None = None,
) -> None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT reddit_id FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        conn.execute(
            """UPDATE drafts
               SET status = ?, decided_at = ?, feedback_reason = ?,
                   final_comment = COALESCE(?, final_comment),
                   assignee = COALESCE(?, assignee),
                   review_notes = COALESCE(?, review_notes),
                   outcome = COALESCE(?, outcome),
                   conversion_value = COALESCE(?, conversion_value)
               WHERE id = ?""",
            (
                status,
                utc_now(),
                feedback_reason,
                final_comment,
                assignee,
                review_notes,
                outcome,
                conversion_value,
                draft_id,
            ),
        )
        if row:
            conn.execute(
                "UPDATE posts SET status = ? WHERE reddit_id = ?",
                (status, row["reddit_id"]),
            )


def move_draft_to_campaign(draft_id: int, target_campaign_key: str) -> None:
    """Move one historical lead into another campaign without losing its source post."""
    with get_db() as conn:
        draft = conn.execute(
            "SELECT reddit_id, campaign_key FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if draft is None:
            raise KeyError(f"Unknown lead: {draft_id}")
        if draft["campaign_key"] == target_campaign_key:
            return
        post = conn.execute(
            "SELECT * FROM posts WHERE reddit_id = ?", (draft["reddit_id"],)
        ).fetchone()
        if post is None:
            raise KeyError(f"Source post for lead {draft_id} no longer exists")
        source_id = post["source_reddit_id"] or post["reddit_id"]
        destination_id = _storage_reddit_id(source_id, target_campaign_key)
        destination = conn.execute(
            "SELECT 1 FROM posts WHERE reddit_id = ?", (destination_id,)
        ).fetchone()
        if destination is None:
            conn.execute(
                """INSERT INTO posts (
                    reddit_id, source_reddit_id, campaign_key, title, subreddit,
                    permalink, url, author, selftext, query, created_utc,
                    first_seen_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    destination_id, source_id, target_campaign_key, post["title"],
                    post["subreddit"], post["permalink"], post["url"], post["author"],
                    post["selftext"], post["query"], post["created_utc"],
                    post["first_seen_at"], post["status"],
                ),
            )
        conn.execute(
            "UPDATE drafts SET reddit_id = ?, campaign_key = ? WHERE id = ?",
            (destination_id, target_campaign_key, draft_id),
        )
        remaining = conn.execute(
            "SELECT COUNT(*) AS count FROM drafts WHERE reddit_id = ?", (draft["reddit_id"],)
        ).fetchone()
        if remaining and not remaining["count"]:
            conn.execute("DELETE FROM posts WHERE reddit_id = ?", (draft["reddit_id"],))


def mark_slack_notified(draft_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE drafts SET slack_notified_at = ? WHERE id = ?",
            (utc_now(), draft_id),
        )


def mark_email_notified(draft_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE drafts SET email_notified_at = ? WHERE id = ?",
            (utc_now(), draft_id),
        )


def recent_generated_comments(
    limit: int = 20, campaign_key: str | None = None
) -> list[str]:
    with get_db() as conn:
        sql = """
            SELECT COALESCE(NULLIF(generated_draft, ''), comment_text) AS comment
            FROM drafts
            WHERE COALESCE(NULLIF(generated_draft, ''), comment_text) != ''
        """
        params: list[object] = []
        if campaign_key:
            sql += " AND campaign_key = ?"
            params.append(campaign_key)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [row["comment"] for row in rows]


def list_leads(
    limit: int = 50, campaign_key: str | None = None
) -> list[sqlite3.Row]:
    with get_db() as conn:
        sql = """
            SELECT
                drafts.id,
                drafts.intent_score,
                drafts.reason,
                drafts.comment_text,
                drafts.status,
                drafts.response_type,
                drafts.should_reply,
                drafts.should_mention_brand,
                drafts.should_include_link,
                drafts.strategy_reason,
                drafts.relevance_score,
                drafts.purchase_intent_score,
                drafts.product_fit_score,
                drafts.urgency_score,
                drafts.reachability_score,
                drafts.promotion_risk_score,
                drafts.market_fit_score,
                drafts.positive_signals,
                drafts.negative_signals,
                drafts.feedback_reason,
                drafts.final_comment,
                drafts.campaign_key,
                drafts.assignee,
                drafts.review_notes,
                drafts.outcome,
                drafts.conversion_value,
                drafts.generated_draft,
                drafts.slack_notified_at,
                drafts.email_notified_at,
                drafts.created_at,
                posts.source_reddit_id AS reddit_id,
                posts.title,
                posts.subreddit,
                posts.permalink,
                posts.author,
                posts.query,
                posts.selftext
            FROM drafts
            JOIN posts ON posts.reddit_id = drafts.reddit_id
        """
        params: list[object] = []
        if campaign_key:
            sql += " WHERE drafts.campaign_key = ?"
            params.append(campaign_key)
        # Keep actionable leads (new/approved/replied) ahead of skipped ones so
        # a high volume of recent skips can't push them past the LIMIT window and
        # out of the rendered card list. Without this, the dashboard stat counts
        # (computed over all rows) disagree with what the status filters can show
        # (which only toggle the rows that were actually rendered).
        sql += " ORDER BY (drafts.status = 'skipped') ASC, drafts.created_at DESC LIMIT ?"
        params.append(limit)
        return conn.execute(sql, params).fetchall()


def lead_stats(campaign_key: str | None = None) -> dict:
    with get_db() as conn:
        clause = " WHERE campaign_key = ?" if campaign_key else ""
        params = (campaign_key,) if campaign_key else ()
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS count FROM drafts{clause} GROUP BY status",
            params,
        ).fetchall()
        total_posts = conn.execute(
            f"SELECT COUNT(*) AS count FROM posts{clause}", params
        ).fetchone()
        lead_clause = " WHERE status != 'skipped'"
        lead_params: tuple[object, ...] = ()
        if campaign_key:
            lead_clause += " AND campaign_key = ?"
            lead_params = (campaign_key,)
        total_leads = conn.execute(
            f"SELECT COUNT(*) AS count FROM drafts{lead_clause}", lead_params
        ).fetchone()
        outcomes = conn.execute(
            f"""SELECT outcome, COUNT(*) AS count,
                       COALESCE(SUM(conversion_value), 0) AS value
                FROM drafts{clause}
                GROUP BY outcome""",
            params,
        ).fetchall()
        replied = next((int(row["count"]) for row in rows if row["status"] == "replied"), 0)
        qualified = sum(
            int(row["count"])
            for row in outcomes
            if row["outcome"] in {"qualified_lead", "converted"}
        )
        return {
            "posts_seen": int(total_posts["count"]),
            "leads_total": int(total_leads["count"]),
            "by_status": {row["status"]: int(row["count"]) for row in rows},
            "by_outcome": {row["outcome"]: int(row["count"]) for row in outcomes},
            "conversion_value": sum(float(row["value"] or 0) for row in outcomes),
            "qualified_rate": (qualified / replied) if replied else 0,
        }
