"""Reliable Reddit discovery through Perplexity with an Apify fallback.

The module deliberately exposes the same normalized post shape used by the
rest of the application. Provider-specific payloads never leak into the AI,
database, or dashboard layers.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app.campaign import Campaign
from app.config import get_settings


logger = logging.getLogger(__name__)

# Reddit links appear in several forms in search-provider responses.  Do not
# require a trailing slash, and allow query strings/fragments after the post
# id.  The old expression silently discarded otherwise valid results.
REDDIT_ID_RE = re.compile(r"/comments/([a-z0-9]+)(?:/|$|[?#])", re.IGNORECASE)
SUBREDDIT_RE = re.compile(r"/r/([^/]+)(?:/|$|[?#])", re.IGNORECASE)
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

_DISCOVERY_STATS: dict[str, object] = {}


class DiscoveryError(RuntimeError):
    """A configured discovery provider could not complete the search."""


class DiscoveryConfigurationError(DiscoveryError):
    """No usable discovery provider has been configured by the operator."""


class ProviderRequestError(DiscoveryError):
    def __init__(self, provider: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


def begin_discovery_scan(campaign: Campaign) -> None:
    queries = build_search_queries(campaign)
    _DISCOVERY_STATS.clear()
    _DISCOVERY_STATS.update(
        {
            "discovery_provider": "perplexity",
            "queries_planned": len(queries),
            "perplexity_requests": 0,
            "perplexity_results": 0,
            "apify_triggered": False,
            "apify_requests": 0,
            "apify_results": 0,
            "provider_errors": [],
            "results_before_dedupe": 0,
            "results_after_dedupe": 0,
            "results_rejected_not_post": 0,
            "results_rejected_excluded_subreddit": 0,
            "results_rejected_excluded_term": 0,
            "results_rejected_age": 0,
            "results_rejected_filter": 0,
        }
    )


def get_discovery_stats() -> dict:
    return dict(_DISCOVERY_STATS)


def build_search_queries(campaign: Campaign) -> list[str]:
    """Build broad search prompts plus optional community refinements.

    Keep original buyer-language queries intact. They have the best recall with
    Perplexity's hybrid lexical and semantic Search API. A community-specific
    variation is supplemental rather than replacing the original phrase, so
    selecting core subreddits never narrows discovery by accident.
    """
    settings = get_settings()
    keywords = _unique(campaign.discovery.keywords)
    core_subreddits = _unique(
        [
            item.strip().removeprefix("r/")
            for item in campaign.discovery.subreddits
            if item.strip() and item.strip().casefold() != "all"
        ]
    )
    product_name = campaign.product.name.strip()
    intent_queries: list[str] = []
    if product_name:
        intent_queries.extend(
            [
                f"{product_name} alternatives",
                f"{product_name} pricing upgrade",
                f"{product_name} review implementation",
            ]
        )
    for competitor in _unique(campaign.product.competitors)[:6]:
        intent_queries.extend(
            [
                f"switch from {competitor}",
                f"{competitor} alternative CRM",
            ]
        )
    queries = _unique([*keywords, *intent_queries])
    community_queries: list[str] = []
    for index, keyword in enumerate(keywords):
        if not core_subreddits:
            break
        subreddit = core_subreddits[index % len(core_subreddits)]
        community_queries.append(f"{keyword} r/{subreddit}")
    queries.extend(community_queries)
    return queries[: settings.discovery_max_queries_per_scan]


def search_posts(
    campaign: Campaign,
    campaign_key: str = "default",
    **_: object,
) -> list[dict]:
    """Search with Perplexity, then supplement through Apify when needed."""
    del campaign_key  # Kept in the signature for scanner and extension compatibility.
    settings = get_settings()
    begin_discovery_scan(campaign)
    queries = build_search_queries(campaign)
    if not queries:
        return []

    primary_posts: list[dict] = []
    primary_failed = False
    if settings.perplexity_api_key:
        try:
            primary_posts = _search_perplexity(queries, campaign)
        except ProviderRequestError as exc:
            primary_failed = True
            _record_provider_error(exc)
            logger.warning("Perplexity discovery failed; considering Apify fallback: %s", exc)
    else:
        primary_failed = True
        _record_provider_error(
            ProviderRequestError("perplexity", "PERPLEXITY_API_KEY is not configured")
        )

    fallback_needed = primary_failed or (
        len(primary_posts) < settings.apify_fallback_min_results
    )
    fallback_posts: list[dict] = []
    if fallback_needed and settings.apify_fallback_enabled and settings.apify_api_token:
        _DISCOVERY_STATS["apify_triggered"] = True
        try:
            fallback_posts = _search_apify(queries, campaign)
        except ProviderRequestError as exc:
            _record_provider_error(exc)
            logger.warning("Apify fallback failed: %s", exc)

    if not settings.perplexity_api_key and not (
        settings.apify_fallback_enabled and settings.apify_api_token
    ):
        raise DiscoveryConfigurationError(
            "Add PERPLEXITY_API_KEY to the server. APIFY_API_TOKEN is optional fallback."
        )

    if primary_failed and not primary_posts and not fallback_posts:
        raise DiscoveryError(
            "No discovery provider returned results. Check the provider status and API credentials."
        )

    combined = [*primary_posts, *fallback_posts]
    _DISCOVERY_STATS["results_before_dedupe"] = len(combined)
    posts = _deduplicate_and_filter(combined, campaign)
    # Search providers occasionally return a stale or missing publication date
    # even when the recency filter was applied server-side. If every valid
    # Reddit result would otherwise disappear, keep the candidates and let the
    # AI qualification stage decide whether they are actionable. This prevents
    # a healthy search response from becoming scanned=0 solely due to metadata.
    posts = _rank_discovered_posts(posts, campaign)
    _DISCOVERY_STATS["results_after_dedupe"] = len(posts)
    logger.info(
        "discovery provider=%s queries=%s requests=%s raw_results=%s "
        "valid_reddit_posts=%s after_filters=%s rejected_not_post=%s "
        "rejected_subreddit=%s rejected_term=%s rejected_age=%s",
        _DISCOVERY_STATS.get("discovery_provider"),
        _DISCOVERY_STATS.get("queries_planned", 0),
        _DISCOVERY_STATS.get("perplexity_requests", 0),
        _DISCOVERY_STATS.get("perplexity_raw_results", 0),
        _DISCOVERY_STATS.get("perplexity_results", 0),
        _DISCOVERY_STATS.get("results_after_dedupe", 0),
        _DISCOVERY_STATS.get("results_rejected_not_post", 0),
        _DISCOVERY_STATS.get("results_rejected_excluded_subreddit", 0),
        _DISCOVERY_STATS.get("results_rejected_excluded_term", 0),
        _DISCOVERY_STATS.get("results_rejected_age", 0),
    )
    if fallback_posts and primary_posts:
        _DISCOVERY_STATS["discovery_provider"] = "perplexity+apify"
    elif fallback_posts:
        _DISCOVERY_STATS["discovery_provider"] = "apify"
    return posts


def research_website_with_perplexity(website_url: str) -> dict:
    """Return public website snippets when direct page fetching is blocked."""
    settings = get_settings()
    if not settings.perplexity_api_key:
        raise DiscoveryConfigurationError("PERPLEXITY_API_KEY is not configured")
    parsed = urlparse(website_url)
    hostname = (parsed.hostname or "").casefold()
    if not hostname:
        raise DiscoveryError("The product website hostname is missing.")
    queries = [
        f"{hostname} product features use cases",
        f"{hostname} pricing customers alternatives",
    ]
    payload = {
        "query": queries,
        "search_domain_filter": [hostname],
        "max_results": 10,
        "search_context_size": "high",
    }
    response = _request_json(
        provider="perplexity",
        url=settings.perplexity_search_url,
        payload=payload,
        token=settings.perplexity_api_key,
        timeout=settings.perplexity_timeout_seconds,
        max_retries=settings.perplexity_max_retries,
    )
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list) or not results:
        raise DiscoveryError("Perplexity did not find readable pages for this website.")
    sections: list[str] = []
    for item in results[:10]:
        if not isinstance(item, dict):
            continue
        sections.append(
            "\n".join(
                [
                    f"SOURCE PAGE: {item.get('url') or website_url}",
                    f"TITLE: {item.get('title') or ''}",
                    str(item.get("snippet") or "")[:6000],
                ]
            )
        )
    if not sections:
        raise DiscoveryError("Perplexity returned no usable website text.")
    return {
        "final_url": website_url,
        "prompt_text": "\n\n".join(sections)[:45000],
        "pages_read": len(sections),
    }


def _search_perplexity(queries: list[str], campaign: Campaign) -> list[dict]:
    settings = get_settings()
    posts: list[dict] = []
    # Perplexity's Search API request schema uses one string in `query`.
    # Sending arrays here was accepted by some early API builds but could
    # return an empty result set without an HTTP error.
    for query in queries:
        payload = {
            "query": query,
            "search_domain_filter": ["reddit.com"],
            "search_recency_filter": _lookback(campaign.discovery.lookback),
            "max_results": min(
                20,
                settings.perplexity_max_results_per_query,
                campaign.discovery.limit_per_keyword,
            ),
            "search_context_size": "high",
        }
        response = _request_json(
            provider="perplexity",
            url=settings.perplexity_search_url,
            payload=payload,
            token=settings.perplexity_api_key,
            timeout=settings.perplexity_timeout_seconds,
            max_retries=settings.perplexity_max_retries,
        )
        _DISCOVERY_STATS["perplexity_requests"] = int(
            _DISCOVERY_STATS.get("perplexity_requests", 0)
        ) + 1
        results = response.get("results") if isinstance(response, dict) else None
        if not isinstance(results, list):
            raise ProviderRequestError(
                "perplexity", "Perplexity returned an invalid Search API response."
            )
        _DISCOVERY_STATS["perplexity_raw_results"] = int(
            _DISCOVERY_STATS.get("perplexity_raw_results", 0)
        ) + len(results)
        for item in results:
            normalized = _normalize_perplexity_post(item, [query])
            if normalized:
                posts.append(normalized)
            else:
                _DISCOVERY_STATS["results_rejected_not_post"] = int(
                    _DISCOVERY_STATS.get("results_rejected_not_post", 0)
                ) + 1
    _DISCOVERY_STATS["perplexity_results"] = len(posts)
    return posts


def _search_apify(queries: list[str], campaign: Campaign) -> list[dict]:
    settings = get_settings()
    actor_id = quote(settings.apify_reddit_actor_id.strip(), safe="~-")
    url = (
        f"https://api.apify.com/v2/actors/{actor_id}/"
        "run-sync-get-dataset-items"
    )
    payload = {
        "searchTerms": queries,
        "searchPosts": True,
        "searchComments": False,
        "searchCommunities": False,
        "searchSort": _apify_sort(campaign.discovery.sort),
        "searchTime": _lookback(campaign.discovery.lookback),
        "maxPostsCount": settings.apify_max_results_per_scan,
        "maxCommentsCount": 0,
        "crawlCommentsPerPost": False,
        "includeNSFW": False,
        "aiAnalysis": False,
    }
    response = _request_json(
        provider="apify",
        url=url,
        payload=payload,
        token=settings.apify_api_token,
        timeout=settings.apify_timeout_seconds,
        max_retries=1,
    )
    _DISCOVERY_STATS["apify_requests"] = int(
        _DISCOVERY_STATS.get("apify_requests", 0)
    ) + 1
    if not isinstance(response, list):
        raise ProviderRequestError("apify", "Apify returned an invalid Actor dataset.")
    posts = []
    for item in response:
        normalized = _normalize_apify_post(item)
        if normalized:
            posts.append(normalized)
    _DISCOVERY_STATS["apify_results"] = len(posts)
    return posts


def _request_json(
    *,
    provider: str,
    url: str,
    payload: dict,
    token: str,
    timeout: int,
    max_retries: int,
):
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "reddit-lead-finder/0.7.5",
        },
    )
    attempts = max(0, max_retries) + 1
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            last_error = exc
            detail = _http_error_detail(exc)
            if exc.code not in RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
                raise ProviderRequestError(
                    provider,
                    f"{provider.title()} request failed with HTTP {exc.code}: {detail}",
                    exc.code,
                ) from exc
            _sleep_for_retry(exc, attempt)
        except (URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            # ConnectionError covers RemoteDisconnected/ConnectionReset, which the
            # search provider raises intermittently when it drops a keep-alive
            # connection mid-response. Retry it instead of surfacing a 500.
            last_error = exc
            if attempt + 1 >= attempts:
                raise ProviderRequestError(
                    provider, f"{provider.title()} request failed: {exc}"
                ) from exc
            _sleep_for_retry(None, attempt)
    raise ProviderRequestError(provider, f"{provider.title()} request failed: {last_error}")


def _normalize_perplexity_post(item: object, queries: list[str]) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = str(
        item.get("url")
        or item.get("permalink")
        or item.get("link")
        or item.get("source_url")
        or ""
    ).strip()
    # Some providers include the Reddit fullname separately even when the
    # displayed URL is shortened.  Use it as a safe fallback identity.
    raw_id = str(
        item.get("reddit_id") or item.get("post_id") or item.get("id") or ""
    ).strip()
    reddit_id = _reddit_id(url) or raw_id.removeprefix("t3_")
    # A few search results expose the post identity and subreddit separately.
    # Reconstruct a canonical permalink so those results still enter the
    # normal scanner pipeline instead of being silently discarded.
    if reddit_id and not url:
        community = str(item.get("subreddit") or item.get("subreddit_name") or "").strip()
        if community:
            url = f"https://www.reddit.com/r/{community.removeprefix('r/')}/comments/{reddit_id}/"
    if not reddit_id or not _is_reddit_url(url):
        return None
    title = str(item.get("title") or "").strip()
    snippet = str(
        item.get("snippet") or item.get("description") or item.get("text") or ""
    ).strip()
    return {
        "reddit_id": reddit_id,
        "title": title or "Reddit discussion",
        "subreddit": _subreddit(url),
        "permalink": url,
        "url": url,
        "author": None,
        "selftext": snippet,
        "created_utc": _timestamp(item.get("date") or item.get("published_date")),
        "query": _best_query(title, snippet, queries),
        "source_provider": "perplexity",
    }


def _normalize_apify_post(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    if item.get("dataType") not in {None, "post"}:
        return None
    url = str(item.get("postUrl") or item.get("url") or "").strip()
    raw_id = str(item.get("parsedId") or item.get("id") or "").strip()
    reddit_id = raw_id.removeprefix("t3_") or _reddit_id(url)
    if not reddit_id or not _is_reddit_url(url):
        return None
    community = str(
        item.get("subredditName") or item.get("communityName") or _subreddit(url)
    ).strip().removeprefix("r/")
    return {
        "reddit_id": reddit_id,
        "title": str(item.get("title") or "Reddit discussion").strip(),
        "subreddit": community or "unknown",
        "permalink": url,
        "url": str(item.get("contentUrl") or url),
        "author": item.get("authorName") or item.get("author"),
        "selftext": str(item.get("body") or item.get("selftext") or "").strip(),
        "created_utc": _timestamp(item.get("createdAt") or item.get("created_utc")),
        "query": str(item.get("searchTerm") or "Apify fallback").strip(),
        "source_provider": "apify",
    }


def _deduplicate_and_filter(posts: list[dict], campaign: Campaign) -> list[dict]:
    by_id: dict[str, dict] = {}
    excluded = {item.casefold().removeprefix("r/") for item in campaign.discovery.excluded_subreddits}
    now = time.time()
    lookback_seconds = {
        "hour": 60 * 60,
        "day": 24 * 60 * 60,
        "week": 7 * 24 * 60 * 60,
        "month": 31 * 24 * 60 * 60,
        "year": 365 * 24 * 60 * 60,
    }.get(campaign.discovery.lookback, 7 * 24 * 60 * 60)
    configured_max_age = campaign.qualification.max_post_age_days * 24 * 60 * 60
    # Enforce the tighter of the Discovery window and Qualification maximum.
    # A campaign set to Past week must never surface a 30-day-old post merely
    # because the separate maximum-post-age field is broader.
    max_age = min(lookback_seconds, configured_max_age)
    for post in posts:
        if post.get("subreddit", "").casefold() in excluded:
            _DISCOVERY_STATS["results_rejected_excluded_subreddit"] = int(
                _DISCOVERY_STATS.get("results_rejected_excluded_subreddit", 0)
            ) + 1
            continue
        if not _market_candidate(post, campaign):
            _DISCOVERY_STATS["results_rejected_excluded_term"] = int(
                _DISCOVERY_STATS.get("results_rejected_excluded_term", 0)
            ) + 1
            continue
        created = post.get("created_utc")
        if created is not None:
            try:
                if now - float(created) > max_age:
                    _DISCOVERY_STATS["results_rejected_age"] = int(
                        _DISCOVERY_STATS.get("results_rejected_age", 0)
                    ) + 1
                    continue
            except (TypeError, ValueError):
                pass
        reddit_id = str(post.get("reddit_id") or "")
        if not reddit_id:
            continue
        existing = by_id.get(reddit_id)
        if existing is None:
            by_id[reddit_id] = post
        else:
            _merge_post(existing, post)
    return list(by_id.values())


def _merge_post(existing: dict, candidate: dict) -> None:
    if len(candidate.get("selftext") or "") > len(existing.get("selftext") or ""):
        existing["selftext"] = candidate.get("selftext") or ""
    for field in ("author", "created_utc", "subreddit"):
        if not existing.get(field) and candidate.get(field):
            existing[field] = candidate[field]
    sources = set(str(existing.get("source_provider") or "").split("+"))
    sources.add(str(candidate.get("source_provider") or ""))
    existing["source_provider"] = "+".join(sorted(item for item in sources if item))


def _rank_discovered_posts(posts: list[dict], campaign: Campaign) -> list[dict]:
    """Put recent evaluation and migration conversations before generic mentions."""
    intent_phrases = {
        "recommend": 4,
        "recommendation": 4,
        "alternative": 4,
        "switch": 4,
        "migrate": 4,
        "migration": 4,
        "replace": 4,
        "comparing": 4,
        "compare": 3,
        "pricing": 3,
        "price": 2,
        "cost": 2,
        "upgrade": 3,
        "evaluating": 4,
        "looking for": 4,
        "we need": 3,
        "trial": 3,
        "implementation": 2,
    }
    product_name = campaign.product.name.strip()
    product_terms = _unique(
        [
            product_name,
            product_name.split("(", 1)[0].strip(),
            product_name.split()[0] if product_name else "",
            *campaign.product.competitors,
        ]
    )
    now = time.time()

    def score(post: dict) -> tuple[float, float]:
        title = str(post.get("title") or "").casefold()
        body = str(post.get("selftext") or "").casefold()
        # The matched query describes what we asked Perplexity to find, not what
        # the author actually wrote. Including it here made every noisy result
        # from an "alternative" query look high-intent. Rank only source content
        # and give the author's title extra weight.
        intent = float(
            sum((weight * 2) for phrase, weight in intent_phrases.items() if phrase in title)
            + sum(weight for phrase, weight in intent_phrases.items() if phrase in body)
        )
        intent += 3.0 * sum(term.casefold() in title for term in product_terms if term)
        intent += 1.5 * sum(term.casefold() in body for term in product_terms if term)
        if "?" in title:
            intent += 2.0
        created = post.get("created_utc")
        recency = 0.0
        if created is not None:
            try:
                age_days = max(0.0, (now - float(created)) / (24 * 60 * 60))
                recency = max(0.0, 7.0 - min(age_days, 7.0)) / 7.0
            except (TypeError, ValueError):
                pass
        post["discovery_priority"] = round(intent + recency, 3)
        return post["discovery_priority"], float(created or 0)

    return sorted(posts, key=score, reverse=True)


def _market_candidate(post: dict, campaign: Campaign) -> bool:
    del post, campaign
    # Market signals and excluded terms require context. A hard substring filter
    # would reject statements such as "we outgrew a free CRM and need a paid
    # replacement". Preserve candidates here and let semantic AI qualification
    # distinguish explicit mismatches from buying-intent language.
    return True


def _record_provider_error(exc: ProviderRequestError) -> None:
    errors = list(_DISCOVERY_STATS.get("provider_errors") or [])
    errors.append(
        {
            "provider": exc.provider,
            "message": str(exc),
            "status_code": exc.status_code,
        }
    )
    _DISCOVERY_STATS["provider_errors"] = errors


def _best_query(title: str, snippet: str, queries: list[str]) -> str:
    haystack = f"{title} {snippet}".casefold()
    best = ""
    best_score = -1
    for query in queries:
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", query.casefold())
            if len(token) > 2 and not token.startswith("reddit")
        }
        score = sum(token in haystack for token in tokens)
        if score > best_score:
            best = query
            best_score = score
    return best or (queries[0] if queries else "")


def _reddit_id(url: str) -> str | None:
    match = REDDIT_ID_RE.search(url)
    return match.group(1) if match else None


def _subreddit(url: str) -> str:
    match = SUBREDDIT_RE.search(url)
    return match.group(1) if match else "unknown"


def _is_reddit_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return host == "reddit.com" or host.endswith(".reddit.com")


def _timestamp(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
        except ValueError:
            return None


def _lookback(value: str) -> str:
    return value if value in {"hour", "day", "week", "month", "year"} else "week"


def _apify_sort(value: str) -> str:
    return value if value in {"relevance", "hot", "top", "new", "comments"} else "new"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        normalized = cleaned.casefold()
        if cleaned and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
    return result


def _http_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read(2000).decode("utf-8", errors="replace")
    except Exception:
        body = ""
    return " ".join(body.split())[:500] or str(exc.reason or "request rejected")


def _sleep_for_retry(exc: HTTPError | None, attempt: int) -> None:
    retry_after: float | None = None
    if exc is not None and exc.headers:
        try:
            retry_after = float(exc.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            retry_after = None
    delay = retry_after if retry_after is not None else (2**attempt) + random.uniform(0, 0.5)
    time.sleep(min(max(delay, 0), 15))
