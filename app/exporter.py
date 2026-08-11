import csv
from pathlib import Path

from app.config import get_settings
from app.db import get_draft


CSV_FIELDS = [
    "draft_id",
    "status",
    "created_at",
    "intent_score",
    "subreddit",
    "title",
    "post_url",
    "keyword",
    "reason",
    "response_type",
    "should_reply",
    "relevance_score",
    "purchase_intent_score",
    "product_fit_score",
    "urgency_score",
    "promotion_risk_score",
    "should_mention_brand",
    "strategy_reason",
    "comment_text",
]


def export_lead(draft_id: int) -> None:
    draft = get_draft(draft_id)
    if not draft:
        return

    settings = get_settings()
    _append_csv(Path(settings.leads_csv_path), draft)
    _append_markdown(Path(settings.leads_markdown_path), draft)


def _append_csv(path: Path, draft) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        row = {
            "draft_id": draft["id"],
            "status": draft["status"],
            "created_at": draft["created_at"],
            "intent_score": f"{draft['intent_score']:.2f}",
            "subreddit": f"r/{draft['subreddit']}",
            "title": draft["title"],
            "post_url": draft["permalink"],
            "keyword": draft["query"] or "",
            "reason": draft["reason"],
            "response_type": draft["response_type"] or "",
            "should_reply": bool(draft["should_reply"]),
            "relevance_score": f"{draft['relevance_score']:.2f}",
            "purchase_intent_score": f"{draft['purchase_intent_score']:.2f}",
            "product_fit_score": f"{draft['product_fit_score']:.2f}",
            "urgency_score": f"{draft['urgency_score']:.2f}",
            "promotion_risk_score": f"{draft['promotion_risk_score']:.2f}",
            "should_mention_brand": bool(draft["should_mention_brand"]),
            "strategy_reason": draft["strategy_reason"] or "",
            "comment_text": draft["comment_text"],
        }
        writer.writerow({key: _csv_safe(value) for key, value in row.items()})


def _append_markdown(path: Path, draft) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n".join(
                [
                    "",
                    f"## Lead #{draft['id']} | score {draft['intent_score']:.2f} | {draft['status']}",
                    "",
                    f"- Campaign: {draft['campaign_key']}",
                    f"- Subreddit: r/{draft['subreddit']}",
                    f"- Title: {draft['title']}",
                    f"- Link: {draft['permalink']}",
                    f"- Keyword: {draft['query'] or ''}",
                    f"- Reason: {draft['reason']}",
                    f"- Response type: {draft['response_type'] or ''}",
                    f"- Strategy reason: {draft['strategy_reason'] or ''}",
                    f"- Should mention brand: {bool(draft['should_mention_brand'])}",
                    "",
                    "Suggested comment:",
                    "",
                    "```text",
                    draft["comment_text"],
                    "```",
                    "",
                ]
            )
        )


def _csv_safe(value):
    if not isinstance(value, str):
        return value
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

