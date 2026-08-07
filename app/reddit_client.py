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
import logging

logger = logging.getLogger(__name__)


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
COMMENT_ID_RE = re.compile(r"/comments/([a-z0-9]+)/", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
_FEED_CACHE: dict[str, tuple[float, list[dict]]] = {}
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
}
_CIRCUIT_STATE = "closed"
_CIRCUIT_OPEN_UNTIL = 0.0
_SCAN_429_COUNT = 0
_HALF_OPEN_TEST_USED = False


def search_posts(
    limit_per_keyword: int = 15, campaign: Campaign | None = None
) -> Iterable[dict]:
    settings = get_settings()
    campaign = campaign or get_campaign()
    seen: set[str] = set()
    requested_urls: set[str] = set()
    begin_reddit_scan(campaign)

    if is_circuit_open():
        remaining = circuit_cooldown_remaining_seconds()
        logger.info(
            "Reddit circuit breaker open, skipping scheduled scan, retry in %s minutes",
            int(remaining / 60),
        )
        return

    excluded = {item.lower() for item in campaign.discovery.excluded_subreddits}
    for subreddit_name in campaign.discovery.subreddits:
        for keyword in consolidated_keywords(campaign):
            if should_stop_reddit_requests():
                logger.info("Skipping remaining Reddit RSS requests for this scan")
                return
            feed_url = _build_search_feed_url(subreddit_name, keyword, campaign)
            if feed_url in requested_urls:
                continue
            requested_urls.add(feed_url)
            for post in _read_feed(feed_url, keyword):
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


def _read_feed(feed_url: str, keyword: str) -> list[dict]:
    cached = _cached_feed(feed_url)
    if cached is not None:
        _FETCH_STATS["cached_rss_requests"] += 1
        return cached

    payload = _fetch_feed_with_retries(feed_url)
    if payload is None:
        return []

    posts = _parse_feed(payload, keyword)
    _FEED_CACHE[feed_url] = (time.monotonic(), posts)
    return posts


def _fetch_feed_with_retries(feed_url: str) -> bytes | None:
    settings = get_settings()
    max_retries = max(0, settings.reddit_rss_max_retries)
    attempts = max_retries + 1
    counted_rate_limit = False

    for attempt in range(attempts):
        if should_stop_reddit_requests():
            return None
        mark_request_started()
        request = _reddit_request(feed_url)
        try:
            _FETCH_STATS["rss_requests"] += 1
            with urllib.request.urlopen(request, timeout=30) as response:
                record_reddit_success()
                return response.read()
        except HTTPError as exc:
            if exc.code == 429:
                if not counted_rate_limit:
                    _FETCH_STATS["rate_limited_requests"] += 1
                    counted_rate_limit = True
                record_reddit_429()
                logger.warning(
                    "Reddit RSS returned 429 (%s/%s)",
                    _SCAN_429_COUNT,
                    settings.reddit_429_circuit_breaker_threshold,
                )
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

            if attempt >= max_retries or should_stop_reddit_requests():
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
    _FETCH_STATS["circuit_state"] = _CIRCUIT_STATE


def get_fetch_stats() -> dict:
    _FETCH_STATS["circuit_state"] = _CIRCUIT_STATE
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()
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
    global _SCAN_429_COUNT, _HALF_OPEN_TEST_USED, _CIRCUIT_STATE
    reset_fetch_stats(campaign)
    _SCAN_429_COUNT = 0
    _HALF_OPEN_TEST_USED = False
    if _CIRCUIT_STATE == "open" and circuit_cooldown_remaining_seconds() <= 0:
        _CIRCUIT_STATE = "half_open"
        logger.info("Reddit circuit breaker half-open, testing one request")
    _FETCH_STATS["circuit_state"] = _CIRCUIT_STATE
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()


def is_circuit_open() -> bool:
    return _CIRCUIT_STATE == "open" and circuit_cooldown_remaining_seconds() > 0


def should_stop_reddit_requests() -> bool:
    return is_circuit_open() or (_CIRCUIT_STATE == "half_open" and _HALF_OPEN_TEST_USED)


def mark_request_started() -> None:
    global _HALF_OPEN_TEST_USED
    if _CIRCUIT_STATE == "half_open":
        _HALF_OPEN_TEST_USED = True


def record_reddit_success() -> None:
    global _CIRCUIT_STATE, _CIRCUIT_OPEN_UNTIL
    if _CIRCUIT_STATE == "half_open":
        _CIRCUIT_STATE = "closed"
        _CIRCUIT_OPEN_UNTIL = 0.0
        logger.info("Reddit RSS recovered, circuit breaker closed")
    _FETCH_STATS["circuit_state"] = _CIRCUIT_STATE
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()


def record_reddit_429() -> None:
    global _SCAN_429_COUNT
    _SCAN_429_COUNT += 1
    threshold = max(1, get_settings().reddit_429_circuit_breaker_threshold)
    if _CIRCUIT_STATE == "half_open" or _SCAN_429_COUNT >= threshold:
        open_circuit()


def open_circuit() -> None:
    global _CIRCUIT_STATE, _CIRCUIT_OPEN_UNTIL
    cooldown_seconds = max(1, get_settings().reddit_429_cooldown_minutes) * 60
    _CIRCUIT_STATE = "open"
    _CIRCUIT_OPEN_UNTIL = time.monotonic() + cooldown_seconds
    _FETCH_STATS["circuit_state"] = _CIRCUIT_STATE
    _FETCH_STATS["circuit_breaker_triggered"] = True
    _FETCH_STATS["reddit_cooldown_remaining_seconds"] = circuit_cooldown_remaining_seconds()
    logger.warning(
        "Reddit circuit breaker opened for %s minutes",
        get_settings().reddit_429_cooldown_minutes,
    )


def circuit_cooldown_remaining_seconds() -> int:
    if _CIRCUIT_STATE != "open":
        return 0
    return max(0, int(_CIRCUIT_OPEN_UNTIL - time.monotonic()))


def reset_circuit_breaker() -> None:
    global _CIRCUIT_STATE, _CIRCUIT_OPEN_UNTIL, _SCAN_429_COUNT, _HALF_OPEN_TEST_USED
    _CIRCUIT_STATE = "closed"
    _CIRCUIT_OPEN_UNTIL = 0.0
    _SCAN_429_COUNT = 0
    _HALF_OPEN_TEST_USED = False
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
    market = (campaign or get_campaign()).market
    text = " ".join(
        [
            post.get("title") or "",
            post.get("selftext") or "",
            post.get("subreddit") or "",
            post.get("query") or "",
        ]
    )
    normalized = text.casefold()
    if any(term.casefold() in normalized for term in market.exclude_terms):
        return False
    if not market.require_market_signal:
        return True
    signals = [*market.customer_signals, *market.countries]
    return any(signal.casefold() in normalized for signal in signals)


def _is_recent_candidate(post: dict, campaign: Campaign | None = None) -> bool:
    created = post.get("created_utc")
    if created is None:
        return True
    max_age = (campaign or get_campaign()).qualification.max_post_age_days * 24 * 60 * 60
    try:
        return time.time() - float(created) <= max_age
    except (TypeError, ValueError):
        return True
