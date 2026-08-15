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
from app.discovery import (
    DiscoveryConfigurationError,
    DiscoveryError,
    begin_discovery_scan,
    get_discovery_stats as get_fetch_stats,
    search_posts,
)
from app.exporter import export_lead
from app.notifications.service import notify_new_lead


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
    """Run the provider-backed scan for one campaign or the whole workspace."""
    global _LAST_MANUAL_SCAN_AT

    settings = get_settings()
    if not _SCAN_LOCK.acquire(blocking=False):
        return {"status": "already_running", "message": "A discovery scan is already running."}

    try:
        records = (
            [get_campaign_record(campaign_key)]
            if campaign_key
            else get_campaign_records()
        )
        if not records:
            return {"status": "idle", "message": "No product workspaces are configured."}

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
                    "retry_after_seconds": max(1, wait_seconds),
                }
            _LAST_MANUAL_SCAN_AT = now

        results = [
            _run_scan_unlocked(record.campaign, record.key)
            for record in records
        ]
        if len(results) == 1:
            return results[0]
        return _combine_campaign_results(results)
    finally:
        _SCAN_LOCK.release()


def _combine_campaign_results(results: list[dict]) -> dict:
    numeric_fields = [
        "scanned",
        "new_posts",
        "analyzed",
        "drafted",
        "duplicates",
        "qualification_skips",
        "errors",
        "perplexity_requests",
        "perplexity_results",
        "apify_requests",
        "apify_results",
    ]
    combined = {
        field: sum(int(result.get(field, 0)) for result in results)
        for field in numeric_fields
    }
    statuses = {str(result.get("status")) for result in results}
    if "configuration_error" in statuses:
        status = "configuration_error"
    elif "provider_error" in statuses:
        status = "provider_error"
    elif "completed_with_fallback" in statuses:
        status = "completed_with_fallback"
    else:
        status = "completed"
    combined.update(
        {
            "status": status,
            "campaigns": results,
            "campaign_count": len(results),
        }
    )
    return combined


def _run_scan_unlocked(
    campaign: Campaign | None = None,
    campaign_key: str | None = None,
    feed_tasks: list | None = None,
    manage_reddit_scan: bool = True,
) -> dict:
    """Discover, qualify, and draft while keeping provider failures contained."""
    del feed_tasks, manage_reddit_scan  # Compatibility with the V0.6 scanner API.
    settings = get_settings()
    campaign = campaign or get_campaign()
    campaign_key = campaign_key or campaign_key_for_path(
        getattr(settings, "campaign_path", "campaigns/campaign.yaml")
    )
    begin_discovery_scan(campaign)
    if hasattr(settings, "openai_api_key") and not settings.openai_api_key:
        return _provider_failure_result(
            "configuration_error",
            "Add OPENAI_API_KEY to the server before scanning.",
            campaign,
            campaign_key,
        )
    scanned = 0
    new_posts = 0
    analyzed = 0
    drafted = 0
    errors = 0
    duplicates = 0
    qualification_skips = 0
    seen_scan_posts: list[dict] = []

    try:
        discovered_posts = search_posts(campaign=campaign, campaign_key=campaign_key)
    except DiscoveryConfigurationError as exc:
        return _provider_failure_result(
            "configuration_error", str(exc), campaign, campaign_key
        )
    except DiscoveryError as exc:
        return _provider_failure_result(
            "provider_error", str(exc), campaign, campaign_key
        )

    for post in discovered_posts:
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

        # Mark a post as seen only after AI qualification succeeds. A temporary
        # OpenAI failure therefore remains retryable on the next scan.
        save_post(post, campaign_key=campaign_key)
        new_posts += 1

        if not qualification.get("is_qualified"):
            qualification_skips += 1
            # Keep related candidates visible. A skipped record has no reply
            # draft and never sends a notification, but its source and AI
            # reasoning remain available for recall and campaign tuning.
            save_draft(
                reddit_id=post["reddit_id"],
                intent_score=float(qualification.get("lead_score") or 0),
                reason=(
                    qualification.get("reason")
                    or qualification.get("skip_reason")
                    or "Not qualified."
                ),
                comment_text="",
                response_type="skip",
                should_reply=False,
                should_mention_brand=False,
                should_include_link=False,
                strategy_reason=(
                    qualification.get("skip_reason") or "No reply recommended."
                ),
                qualification=qualification,
                campaign_key=campaign_key,
                status="skipped",
            )
            logger.info(
                "skipping unqualified post reddit_id=%s reason=%s",
                post["reddit_id"],
                qualification.get("skip_reason") or qualification.get("reason"),
            )
            continue

        score = float(qualification["lead_score"])
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
            logger.error(
                "OpenAI draft generation failed for %s: %s", post["reddit_id"], exc
            )
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

    fetch_stats = get_fetch_stats()
    logger.info(
        "scan complete provider=%s queries=%s requests=%s raw_results=%s "
        "valid_results=%s after_filters=%s rejected_not_post=%s scanned=%s "
        "rejected_subreddit=%s rejected_term=%s rejected_age=%s "
        "new=%s analyzed=%s drafted=%s errors=%s",
        fetch_stats.get("discovery_provider"),
        fetch_stats.get("queries_planned", 0),
        fetch_stats.get("perplexity_requests", 0),
        fetch_stats.get("perplexity_raw_results", 0),
        fetch_stats.get("perplexity_results", 0),
        fetch_stats.get("results_after_dedupe", 0),
        fetch_stats.get("results_rejected_not_post", 0),
        scanned,
        fetch_stats.get("results_rejected_excluded_subreddit", 0),
        fetch_stats.get("results_rejected_excluded_term", 0),
        fetch_stats.get("results_rejected_age", 0),
        new_posts,
        analyzed,
        drafted,
        errors,
    )
    status = "completed_with_fallback" if fetch_stats.get("apify_triggered") else "completed"
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


def _provider_failure_result(
    status: str,
    message: str,
    campaign: Campaign,
    campaign_key: str,
) -> dict:
    return {
        "status": status,
        "message": message,
        "campaign_key": campaign_key,
        "campaign_name": campaign.name,
        "scanned": 0,
        "new_posts": 0,
        "analyzed": 0,
        "drafted": 0,
        "duplicates": 0,
        "qualification_skips": 0,
        "errors": 1,
        **get_fetch_stats(),
    }
