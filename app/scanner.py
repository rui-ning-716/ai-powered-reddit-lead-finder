import logging
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from openai import OpenAIError

from app.ai import (
    decide_response_strategy,
    evaluate_opportunity,
    generate_personalized_comment,
)
from app.campaign import (
    Campaign,
    campaign_key_for_path,
    get_campaign,
    get_campaign_record,
    get_campaign_records,
)
from app.config import get_settings
from app.db import has_seen_post, recent_generated_comments, save_draft, save_post
from app.dedupe import find_duplicate_post
from app.exporter import export_lead
from app.notifications.service import notify_new_lead
from app.reddit_client import get_fetch_stats, search_posts

logger = logging.getLogger(__name__)

_SCAN_LOCK = threading.Lock()
_LAST_MANUAL_SCAN_AT: float | None = None
T = TypeVar("T")


def run_when_scan_idle(operation: Callable[[], T]) -> tuple[bool, T | None]:
    """Run a short configuration operation without racing an active scan."""
    if not _SCAN_LOCK.acquire(blocking=False):
        return False, None
    try:
        return True, operation()
    finally:
        _SCAN_LOCK.release()


def run_scan(manual: bool = False, campaign_key: str | None = None) -> dict:
    global _LAST_MANUAL_SCAN_AT

    settings = get_settings()
    if not _SCAN_LOCK.acquire(blocking=False):
        return {"status": "already_running"}

    try:
        if manual:
            cooldown_seconds = settings.min_manual_scan_interval_minutes * 60
            now = time.monotonic()
            if (
                _LAST_MANUAL_SCAN_AT is not None
                and cooldown_seconds > 0
                and now - _LAST_MANUAL_SCAN_AT < cooldown_seconds
            ):
                wait_seconds = int(cooldown_seconds - (now - _LAST_MANUAL_SCAN_AT))
                return {
                    "status": "cooldown",
                    "message": "A manual scan ran recently. Please wait before scanning again.",
                    "retry_after_seconds": wait_seconds,
                }
            _LAST_MANUAL_SCAN_AT = now

        records = (
            [get_campaign_record(campaign_key)]
            if campaign_key
            else get_campaign_records()
        )
        results = [
            _run_scan_unlocked(record.campaign, record.key) for record in records
        ]
        if len(results) == 1:
            return results[0]
        numeric_fields = [
            "scanned", "new_posts", "analyzed", "drafted", "duplicates",
            "qualification_skips", "errors", "rss_requests",
            "cached_rss_requests", "rate_limited_requests", "rss_errors",
        ]
        combined = {
            field: sum(int(result.get(field, 0)) for result in results)
            for field in numeric_fields
        }
        combined.update(
            {
                "status": "completed",
                "campaigns": results,
                "campaign_count": len(results),
            }
        )
        if any(result.get("status") == "reddit_rate_limit_cooldown" for result in results):
            combined["status"] = "reddit_rate_limit_cooldown"
        return combined
    finally:
        _SCAN_LOCK.release()


def _run_scan_unlocked(
    campaign: Campaign | None = None, campaign_key: str | None = None
) -> dict:
    settings = get_settings()
    campaign = campaign or get_campaign()
    campaign_key = campaign_key or campaign_key_for_path(
        getattr(settings, "campaign_path", "campaigns/campaign.yaml")
    )
    scanned = 0
    new_posts = 0
    analyzed = 0
    drafted = 0
    errors = 0
    duplicates = 0
    qualification_skips = 0
    seen_scan_posts: list[dict] = []

    for post in search_posts(campaign=campaign):
        scanned += 1
        if has_seen_post(post["reddit_id"], campaign_key=campaign_key):
            continue

        duplicate = find_duplicate_post(post, seen_scan_posts)
        if duplicate.is_duplicate:
            duplicates += 1
            logger.info(
                "skipping duplicate post reddit_id=%s duplicate_of=%s reason=%s score=%.2f",
                post["reddit_id"],
                duplicate.duplicate_of_reddit_id,
                duplicate.reason,
                duplicate.score,
            )
            continue
        seen_scan_posts.append(post)

        if analyzed >= settings.max_ai_posts_per_scan:
            logger.info("max AI posts per scan reached: %s", settings.max_ai_posts_per_scan)
            break

        new_posts += 1
        save_post(post, campaign_key=campaign_key)
        analyzed += 1

        try:
            qualification = evaluate_opportunity(post, campaign=campaign)
        except OpenAIError as exc:
            errors += 1
            logger.error("OpenAI request failed; stopping this scan: %s", exc)
            break
        except Exception as exc:
            errors += 1
            logger.exception("failed to analyze post %s: %s", post["reddit_id"], exc)
            continue

        if not qualification.get("is_qualified"):
            qualification_skips += 1
            logger.info(
                "skipping unqualified post reddit_id=%s reason=%s",
                post["reddit_id"],
                qualification.get("skip_reason") or qualification.get("reason"),
            )
            continue

        score = float(qualification["lead_score"])
        threshold = campaign.qualification.minimum_lead_score

        if (
            qualification["market_fit"]
            and score >= threshold
        ):
            strategy = decide_response_strategy(post, qualification, campaign=campaign)
            try:
                draft = generate_personalized_comment(
                    post=post,
                    qualification=qualification,
                    strategy=strategy,
                    recent_comments=recent_generated_comments(
                        limit=20, campaign_key=campaign_key
                    ),
                    campaign=campaign,
                )
                comment_text = draft.get("comment_text", "")
            except OpenAIError as exc:
                errors += 1
                logger.error("OpenAI draft generation failed for %s: %s", post["reddit_id"], exc)
                comment_text = ""
            except Exception as exc:
                errors += 1
                logger.exception("failed to generate draft for %s: %s", post["reddit_id"], exc)
                comment_text = ""

            draft_id = save_draft(
                reddit_id=post["reddit_id"],
                intent_score=score,
                reason=qualification["reason"],
                comment_text=comment_text,
                response_type=strategy["response_type"],
                should_reply=strategy["should_reply"],
                should_mention_brand=strategy["should_mention_brand"],
                should_include_link=strategy["should_include_link"],
                strategy_reason=strategy["reason"],
                qualification=qualification,
                campaign_key=campaign_key,
            )
            export_lead(draft_id)
            notify_new_lead(draft_id, campaign=campaign)
            drafted += 1

    logger.info(
        "scan complete scanned=%s new=%s analyzed=%s drafted=%s errors=%s",
        scanned,
        new_posts,
        analyzed,
        drafted,
        errors,
    )
    fetch_stats = get_fetch_stats()
    status = "completed"
    if (
        fetch_stats.get("circuit_state") == "open"
        and fetch_stats.get("rss_requests") == 0
        and scanned == 0
    ):
        status = "reddit_rate_limit_cooldown"

    return {
        "status": status,
        "campaign_key": campaign_key,
        "campaign_name": campaign.name,
        "scanned": scanned,
        "new_posts": new_posts,
        "analyzed": analyzed,
        "drafted": drafted,
        "duplicates": duplicates,
        "qualification_skips": qualification_skips,
        "errors": errors,
        **fetch_stats,
    }
