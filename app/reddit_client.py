import re
import random
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from email.utils import parsedate_to_datetime
from datetime import datetime
from html import unescape
from urllib.error import HTTPError, URLError

from app.config import get_settings
from app.campaign import Campaign, get_campaign
from app.reddit_scan_state import (
    FeedTask,
    get_cooldown_state,
    mark_feed_attempt,
    mark_feed_error,
    mark_feed_success,
    record_rate_limit,
    record_recovery,
    reset_rate_limit_state,
    select_feed_tasks,
    sync_campaign_feeds,
)
import logging

logger = logging.getLogger(__name__)


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
COMMENT_ID_RE = re.compile(r"/comments/([a-z0-9]+)/", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
_FEED_CACHE: dict[str, tuple[float, list[dict]]] = {}
_LAST_RSS_REQUEST_AT: float | None = None
_SCAN_ABORTED = False
_FETCH_STATS = {
    "rss_requests": 0,
    "cached_rss_requests": 0,
    "rate_limited_requests": 0,
    "rss_errors": 0,
    "circuit_state": "closed",
    "circuit_breaker_triggered": False,
    "reddit_cooldown_remaining_seconds": 0,
    "keyword_queries_before_consolidation": 0,
    "keyword_queries_after_consolidation": 0,
    "feeds_selected": 0,
    "feeds_high_intent": 0,
    "feeds_standard": 0,
    "feeds_research": 0,
}

HIGH_INTENT_TERMS = (
    "recommend",
    "alternative",
    "alternatives",
    " vs ",
    "compare",
    "comparison",
    "looking for",
    "need a ",
    "need an ",
    "best ",
    "switch",
    "replace",
    "pricing",
    "price",
    "trial",
    "buy",
    "purchase",
)


def search_posts(
    limit_per_keyword: int = 15,
    campaign: Campaign | None = None,
    campaign_key: str = "default",
    feed_tasks: list[FeedTask] | None = None,
    *,
    force: bool = False,
    manage_scan: bool = True,
) -> Iterable[dict]:
    settings = get_settings()
    campaign = campaign or get_campaign()
    seen: set[str] = set()
    if manage_scan:
        begin_reddit_scan(campaign)

    if is_circuit_open():
        remaining = circuit_cooldown_remaining_seconds()
        logger.info(
            "Reddit circuit breaker open, skipping scheduled scan, retry in %s minutes",
            int(remaining / 60),
        )
        return

    if feed_tasks is None:
        sync_campaign_feeds(campaign_key, build_feed_descriptors(campaign))
        feed_tasks = select_feed_tasks(
            [campaign_key],
            _requests_per_tick(settings),
            force=force,
        )
    _record_selected_feed_stats(feed_tasks, accumulate=not manage_scan)

    excluded = {item.lower() for item in campaign.discovery.excluded_subreddits}
    for task in feed_tasks:
        if should_stop_reddit_requests():
            logger.info("Skipping remaining Reddit RSS requests for this scan")
            return
        for post in _read_feed(
            task.feed_url,
            task.keyword,
            task=task,
        ):
            if post["reddit_id"] in seen:
                continue
            if post.get("subreddit", "").lower() in excluded:
                continue
            if not _is_market_candidate(post, campaign):
                continue
            if not _is_recent_candidate(post, campaign):
                continue
            seen.add(post["reddit_id"])
            yield post


def build_feed_descriptors(campaign: Campaign | None = None) -> list[dict]:
    """Build deduplicated RSS work items and assign their automatic cadence."""
    campaign = campaign or get_campaign()
    excluded = {item.casefold() for item in campaign.discovery.excluded_subreddits}
    core = _unique_subreddits(campaign.discovery.subreddits, excluded)
    research = _unique_subreddits(
        [
            *campaign.discovery.adjacent_subreddits,
            *campaign.discovery.watch_only_subreddits,
        ],
        excluded,
    )
    descriptors: list[dict] = []
    seen_urls: set[str] = set()
    for subreddit_name, community_tier in [
        *((item, "core") for item in core),
        *((item, "research") for item in research if item not in core),
    ]:
        for keyword in consolidated_keywords(campaign):
            feed_url = _build_search_feed_url(subreddit_name, keyword, campaign)
            if feed_url in seen_urls:
                continue
            seen_urls.add(feed_url)
            if community_tier == "research":
                tier = "research"
            else:
                tier = "high" if _is_high_intent_keyword(keyword) else "standard"
            descriptors.append(
                {
                    "feed_url": feed_url,
                    "keyword": keyword,
                    "subreddit": subreddit_name,
                    "tier": tier,
                }
            )
    return descriptors


def _unique_subreddits(items: list[str], excluded: set[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = item.strip().removeprefix("r/")
        normalized = value.casefold()
        if not value or normalized in excluded or normalized in seen:
            continue
        seen.add(normalized)
        result.append(value)
    return result


def _is_high_intent_keyword(keyword: str) -> bool:
    normalized = f" {keyword.casefold().strip().replace(chr(34), '')} "
    return any(term in normalized for term in HIGH_INTENT_TERMS)


def _requests_per_tick(settings) -> int:
    low, high = sorted(
        (
            max(1, settings.reddit_rss_requests_per_tick_min),
            max(1, settings.reddit_rss_requests_per_tick_max),
        )
    )
    return random.randint(low, high)


def _request_spacing_delay(settings) -> float:
    low, high = sorted(
        (
            max(0.0, settings.reddit_rss_request_delay_min_seconds),
            max(0.0, settings.reddit_rss_request_delay_max_seconds),
        )
    )
    return random.uniform(low, high)


def request_budget_for_tick(settings=None) -> int:
    return _requests_per_tick(settings or get_settings())


def _record_selected_feed_stats(
    tasks: list[FeedTask], *, accumulate: bool = False
) -> None:
    values = {
        "feeds_selected": len(tasks),
        "feeds_high_intent": sum(task.tier == "high" for task in tasks),
        "feeds_standard": sum(task.tier == "standard" for task in tasks),
        "feeds_research": sum(task.tier == "research" for task in tasks),
    }
    for field, value in values.items():
        _FETCH_STATS[field] = int(_FETCH_STATS.get(field, 0)) + value if accumulate else value


def _build_search_feed_url(
    subreddit_name: str, keyword: str, campaign: Campaign | None = None
) -> str:
    campaign = campaign or get_campaign()
    params = urllib.parse.urlencode(
        {
            "q": keyword,
            "sort": campaign.discovery.sort,
            "t": campaign.discovery.lookback,
            "limit": str(campaign.discovery.limit_per_keyword),
        }
    )
    if subreddit_name == "all":
        return f"https://www.reddit.com/search.rss?{params}"
    return f"https://www.reddit.com/r/{subreddit_name}/search.rss?{params}&restrict_sr=1"


def _read_feed(
    feed_url: str,
    keyword: str,
    task: FeedTask | None = None,
    delay_before_fetch: float | None = None,
) -> list[dict]:
    cached = _cached_feed(feed_url)
    if cached is not None:
        _FETCH_STATS["cached_rss_requests"] += 1
        if task:
            mark_feed_success(task.id, task.tier)
        return cached

    _wait_before_rss_request(delay_before_fetch)
    if task:
        mark_feed_attempt(task.id)
    payload = _fetch_feed_with_retries(feed_url)
    if payload is None:
        if task:
            state = get_cooldown_state()
            if _FETCH_STATS["rate_limited_requests"] > 0:
                mark_feed_error(
                    task.id,
                    "rate_limited",
                    retry_at=state.cooldown_until,
                )
            else:
                mark_feed_error(task.id, "error")
        return []

    posts = _parse_feed(payload, keyword)
    _FEED_CACHE[feed_url] = (time.monotonic(), posts)
    if task:
        mark_feed_success(task.id, task.tier)
    return posts


def _wait_before_rss_request(delay_override: float | None = None) -> None:
    global _LAST_RSS_REQUEST_AT
    if _LAST_RSS_REQUEST_AT is not None:
        target_delay = (
            _request_spacing_delay(get_settings())
            if delay_override is None
            else max(0.0, delay_override)
        )
        delay = max(0.0, target_delay - (time.monotonic() - _LAST_RSS_REQUEST_AT))
        if delay > 0:
            logger.info("Spacing Reddit RSS requests by %.1f seconds", delay)
            time.sleep(delay)
    _LAST_RSS_REQUEST_AT = time.monotonic()


def _fetch_feed_with_retries(feed_url: str) -> bytes | None:
    settings = get_settings()
    max_retries = max(0, settings.reddit_rss_max_retries)
    attempts = max_retries + 1

    for attempt in range(attempts):
        if should_stop_reddit_requests():
            return None
        request = _reddit_request(feed_url)
        try:
            _FETCH_STATS["rss_requests"] += 1
            with urllib.request.urlopen(request, timeout=30) as response:
                record_reddit_success()
                return response.read()
        except HTTPError as exc:
            if exc.code == 429:
                _FETCH_STATS["rate_limited_requests"] += 1
                retry_after = _retry_after_seconds(exc)
                record_reddit_429(retry_after)
                logger.warning(
                    "Reddit RSS returned 429; stopping this scan and pausing globally"
                )
                return None
            elif 500 <= exc.code <= 599:
                _FETCH_STATS["rss_errors"] += 1
                logger.warning(
                    "Temporary Reddit RSS error url=%s status=%s", feed_url, exc.code
                )
            else:
                _FETCH_STATS["rss_errors"] += 1
                logger.warning(
                    "Non-retryable Reddit RSS error url=%s status=%s", feed_url, exc.code
                )
                return None

            if attempt >= max_retries:
                logger.warning("Reddit RSS request failed after retries url=%s", feed_url)
                return None
            _sleep_before_retry(exc, attempt)
        except URLError as exc:
            _FETCH_STATS["rss_errors"] += 1
            logger.warning("Temporary Reddit RSS network error url=%s error=%s", feed_url, exc)
            if attempt >= max_retries:
                return None
            _sleep_before_retry(None, attempt)
    return None


def _reddit_request(feed_url: str) -> urllib.request.Request:
    request = urllib.request.Request(
        feed_url,
        headers={
            "User-Agent": get_settings().reddit_user_agent,
            "Accept": "application/atom+xml, application/rss+xml, text/xml",
        },
    )
    return request


def _parse_feed(payload: bytes, keyword: str) -> list[dict]:
    root = ET.fromstring(payload)
    posts: list[dict] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title = _entry_text(entry, "title")
        permalink = _entry_link(entry)
        reddit_id = _extract_reddit_id(permalink) or _entry_text(entry, "id")
        if not reddit_id:
            continue

        posts.append(
            {
                "reddit_id": reddit_id,
                "title": title,
                "subreddit": _extract_subreddit(permalink),
                "permalink": permalink,
                "url": permalink,
                "author": _entry_author(entry),
                "selftext": _clean_html(_entry_text(entry, "content") or _entry_text(entry, "summary")),
                "created_utc": _entry_timestamp(entry),
                "query": keyword,
            }
        )
    return posts


def _cached_feed(feed_url: str) -> list[dict] | None:
    cached = _FEED_CACHE.get(feed_url)
    if not cached:
        return None
    fetched_at, posts = cached
    ttl_seconds = get_settings().reddit_rss_cache_ttl_minutes * 60
    if ttl_seconds <= 0 or time.monotonic() - fetched_at > ttl_seconds:
        return None
    return posts


def _sleep_before_retry(error: HTTPError | None, attempt: int) -> None:
    retry_after = _retry_after_seconds(error) if error else None
    delay = retry_after if retry_after is not None else _backoff_delay(attempt)
    logger.warning("Retrying Reddit RSS request in %.1f seconds", delay)
    time.sleep(delay)


def _backoff_delay(attempt: int) -> float:
    base = 30 * (2**attempt)
    return base + random.uniform(0, 5)


def _retry_after_seconds(error: HTTPError | None) -> float | None:
    if not error:
        return None
    value = error.headers.get("Retry-After") if error.headers else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                return None
            return max(0.0, retry_at.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


def reset_fetch_stats(campaign: Campaign | None = None) -> None:
    campaign = campaign or get_campaign()
    configured = campaign.discovery.keywords
    consolidated = consolidated_keywords(campaign)
    _FETCH_STATS["rss_requests"] = 0
    _FETCH_STATS["cached_rss_requests"] = 0
    _FETCH_STATS["rate_limited_requests"] = 0
    _FETCH_STATS["rss_errors"] = 0
    _FETCH_STATS["circuit_breaker_triggered"] = False
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = 0
    _FETCH_STATS["keyword_queries_before_consolidation"] = len(configured)
    _FETCH_STATS["keyword_queries_after_consolidation"] = len(consolidated)
    _FETCH_STATS["feeds_selected"] = 0
    _FETCH_STATS["feeds_high_intent"] = 0
    _FETCH_STATS["feeds_standard"] = 0
    _FETCH_STATS["feeds_research"] = 0
    _FETCH_STATS["circuit_state"] = "open" if is_circuit_open() else "closed"


def get_fetch_stats() -> dict:
    _FETCH_STATS["circuit_state"] = "open" if is_circuit_open() else "closed"
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()
    _FETCH_STATS["reddit_429_strike_count"] = get_cooldown_state().strike_count
    return dict(_FETCH_STATS)


def _unique_keywords(keywords: list[str]) -> list[str]:
    seen: set[str] = set()
    unique = []
    for keyword in keywords:
        normalized = keyword.strip().lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(keyword)
    return unique


def consolidated_keywords(campaign: Campaign | None = None) -> list[str]:
    campaign = campaign or get_campaign()
    return _unique_keywords(campaign.discovery.keywords)


def keyword_consolidation_report(campaign: Campaign | None = None) -> dict:
    campaign = campaign or get_campaign()
    configured = campaign.discovery.keywords
    consolidated = consolidated_keywords(campaign)
    return {
        "before_count": len(configured),
        "after_count": len(consolidated),
        "keywords": consolidated,
    }


def begin_reddit_scan(campaign: Campaign | None = None) -> None:
    global _SCAN_ABORTED
    _SCAN_ABORTED = False
    reset_fetch_stats(campaign)
    _FETCH_STATS["circuit_state"] = "open" if is_circuit_open() else "closed"
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()


def is_circuit_open() -> bool:
    return get_cooldown_state().remaining_seconds() > 0


def should_stop_reddit_requests() -> bool:
    return _SCAN_ABORTED or is_circuit_open()


def record_reddit_success() -> None:
    record_recovery()
    _FETCH_STATS["circuit_state"] = "closed"
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()


def record_reddit_429(retry_after_seconds: float | None = None) -> None:
    global _SCAN_ABORTED
    _SCAN_ABORTED = True
    state = record_rate_limit(retry_after_seconds)
    _FETCH_STATS["circuit_state"] = "open"
    _FETCH_STATS["circuit_breaker_triggered"] = True
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = state.remaining_seconds()


def open_circuit(retry_after_seconds: float | None = None) -> None:
    """Compatibility wrapper for callers that explicitly pause Reddit RSS."""
    record_reddit_429(retry_after_seconds)


def circuit_cooldown_remaining_seconds() -> int:
    return get_cooldown_state().remaining_seconds()


def reset_circuit_breaker() -> None:
    global _SCAN_ABORTED
    _SCAN_ABORTED = False
    reset_rate_limit_state()
    reset_fetch_stats()


def _entry_text(entry: ET.Element, tag: str) -> str:
    node = entry.find(f"atom:{tag}", ATOM_NS)
    return node.text.strip() if node is not None and node.text else ""


def _entry_link(entry: ET.Element) -> str:
    for node in entry.findall("atom:link", ATOM_NS):
        href = node.attrib.get("href")
        if href and "/comments/" in href:
            return href
    node = entry.find("atom:link", ATOM_NS)
    return node.attrib.get("href", "") if node is not None else ""


def _entry_author(entry: ET.Element) -> str | None:
    node = entry.find("atom:author/atom:name", ATOM_NS)
    return node.text.strip() if node is not None and node.text else None


def _entry_timestamp(entry: ET.Element) -> float | None:
    value = _entry_text(entry, "updated") or _entry_text(entry, "published")
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def _extract_reddit_id(url: str) -> str | None:
    match = COMMENT_ID_RE.search(url)
    return match.group(1) if match else None


def _extract_subreddit(url: str) -> str:
    match = re.search(r"/r/([^/]+)/", url, re.IGNORECASE)
    return match.group(1) if match else "unknown"


def _clean_html(value: str) -> str:
    return unescape(TAG_RE.sub(" ", value)).strip()


def _is_market_candidate(post: dict, campaign: Campaign | None = None) -> bool:
    del post, campaign
    # Legacy RSS compatibility path. Market and exclusion evidence is evaluated
    # semantically after discovery, never as an exact pre-AI string gate.
    return True


def _is_recent_candidate(post: dict, campaign: Campaign | None = None) -> bool:
    created = post.get("created_utc")
    if created is None:
        return True
    max_age = (campaign or get_campaign()).qualification.max_post_age_days * 24 * 60 * 60
    try:
        return time.time() - float(created) <= max_age
    except (TypeError, ValueError):
        return True
