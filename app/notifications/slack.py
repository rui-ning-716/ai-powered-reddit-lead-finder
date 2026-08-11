import json
import logging
import urllib.request

from app.config import get_settings
from app.campaign import Campaign, get_campaign

logger = logging.getLogger(__name__)


def send_slack_notification(lead: dict, campaign: Campaign | None = None) -> bool:
    settings = get_settings()
    if not settings.slack_notifications_enabled:
        return False
    if not settings.slack_webhook_url:
        logger.warning("Slack notifications enabled but SLACK_WEBHOOK_URL is missing")
        return False

    payload = {"text": _format_message(lead, campaign=campaign)}
    request = urllib.request.Request(
        settings.slack_webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if 200 <= response.status < 300:
                return True
            logger.warning("Slack webhook returned status %s", response.status)
    except Exception as exc:
        logger.exception("Slack notification failed: %s", exc)
    return False


def _format_message(lead: dict, campaign: Campaign | None = None) -> str:
    campaign = campaign or get_campaign()
    draft = _truncate(lead.get("comment_text") or "", 1800)
    return "\n".join(
        [
            f"🔥 New Reddit Opportunity for {campaign.product.name}",
            f"Campaign: {campaign.name}",
            "",
            f"Lead score: {float(lead['intent_score']):.2f}",
            f"Purchase intent: {float(lead.get('purchase_intent_score') or 0):.2f}",
            f"Product fit: {float(lead.get('product_fit_score') or 0):.2f}",
            f"Response type: {_label(lead.get('response_type'))}",
            f"Subreddit: r/{lead.get('subreddit') or 'unknown'}",
            "",
            "Title:",
            lead.get("title") or "Untitled",
            "",
            "Why this is worth replying to:",
            lead.get("strategy_reason") or lead.get("reason") or "",
            "",
            "Suggested response:",
            draft or "(No draft generated.)",
            "",
            "Reddit:",
            lead.get("permalink") or "",
        ]
    )


def _label(value: str | None) -> str:
    return (value or "helpful_only").replace("_", " ").title()


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."

