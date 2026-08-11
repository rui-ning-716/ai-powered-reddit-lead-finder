import re
from dataclasses import dataclass
from difflib import SequenceMatcher


SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class DuplicateMatch:
    is_duplicate: bool
    duplicate_of_reddit_id: str | None = None
    reason: str = ""
    score: float = 0.0


def find_duplicate_post(post: dict, seen_posts: list[dict]) -> DuplicateMatch:
    for existing in seen_posts:
        if post.get("reddit_id") == existing.get("reddit_id"):
            return DuplicateMatch(True, existing.get("reddit_id"), "same_reddit_id", 1.0)

        if not _within_window(post, existing):
            continue

        title_similarity = similarity(post.get("title", ""), existing.get("title", ""))
        body_similarity = similarity(post.get("selftext", ""), existing.get("selftext", ""))
        same_author = _same_author(post, existing)

        if normalized_text(post.get("title", "")) == normalized_text(existing.get("title", "")):
            return DuplicateMatch(
                True,
                existing.get("reddit_id"),
                "cross_post_duplicate_exact_title",
                max(title_similarity, body_similarity),
            )

        if title_similarity >= 0.9 and body_similarity >= 0.72:
            return DuplicateMatch(
                True,
                existing.get("reddit_id"),
                "cross_post_duplicate_similar_title_body",
                (title_similarity + body_similarity) / 2,
            )

        if same_author and title_similarity >= 0.86 and body_similarity >= 0.5:
            return DuplicateMatch(
                True,
                existing.get("reddit_id"),
                "cross_post_duplicate_same_author",
                (title_similarity + body_similarity) / 2,
            )

    return DuplicateMatch(False)


def normalized_text(value: str) -> str:
    value = value.lower()
    value = re.sub(r"\b(r/)?[a-z0-9_]+ subreddit\b", " ", value)
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def similarity(left: str, right: str) -> float:
    left_norm = normalized_text(left)
    right_norm = normalized_text(right)
    if not left_norm or not right_norm:
        return 1.0 if left_norm == right_norm else 0.0
    sequence_score = SequenceMatcher(None, left_norm, right_norm).ratio()
    token_score = _jaccard(left_norm, right_norm)
    return max(sequence_score, token_score)


def _jaccard(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _same_author(post: dict, existing: dict) -> bool:
    author = (post.get("author") or "").lower().strip()
    existing_author = (existing.get("author") or "").lower().strip()
    return bool(author and existing_author and author == existing_author)


def _within_window(post: dict, existing: dict) -> bool:
    left = post.get("created_utc")
    right = existing.get("created_utc")
    if left is None or right is None:
        return True
    try:
        return abs(float(left) - float(right)) <= SEVEN_DAYS_SECONDS
    except (TypeError, ValueError):
        return True

