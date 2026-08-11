import logging

from app.config import get_settings
from app.campaign import Campaign, get_campaign, get_campaign_record
from app.db import get_draft, mark_email_notified, mark_slack_notified
from app.notifications.email import send_email_notification
from app.notifications.slack import send_slack_notification

logger = logging.getLogger(__name__)


def notify_new_lead(draft_id: int, campaign: Campaign | None = None) -> dict:
    draft = get_draft(draft_id)
    if not draft:
        return {"slack": False, "email": False}

    lead = dict(draft)
    result = {"slack": False, "email": False}
    if campaign is None:
        try:
            campaign = get_campaign_record(lead.get("campaign_key")).campaign
        except (KeyError, FileNotFoundError):
            campaign = get_campaign()
    if not should_notify(lead, campaign):
        return result

    settings = get_settings()

    try:
        if (
            settings.slack_notifications_enabled
            and not lead.get("slack_notified_at")
            and _passes_slack_threshold(lead)
        ):
            result["slack"] = send_slack_notification(lead, campaign=campaign)
            if result["slack"]:
                mark_slack_notified(draft_id)
    except Exception as exc:
        logger.exception("Slack notification service failed for draft %s: %s", draft_id, exc)

    try:
        if settings.email_notifications_enabled and not lead.get("email_notified_at"):
            result["email"] = send_email_notification(lead)
            if result["email"]:
                mark_email_notified(draft_id)
    except Exception as exc:
        logger.exception("Email notification service failed for draft %s: %s", draft_id, exc)

    return result


def should_notify(lead: dict, campaign: Campaign | None = None) -> bool:
    campaign = campaign or get_campaign()
    return (
        bool(lead.get("should_reply"))
        and lead.get("response_type") != "skip"
        and float(lead.get("intent_score") or 0)
        >= campaign.qualification.minimum_lead_score
    )


def _passes_slack_threshold(lead: dict) -> bool:
    return float(lead.get("intent_score") or 0) >= get_settings().slack_min_intent_score

