import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_email_notification(lead: dict) -> bool:
    settings = get_settings()
    if not settings.email_notifications_enabled:
        return False

    missing = _missing_settings(settings)
    if missing:
        logger.warning("Email notifications enabled but missing config: %s", ", ".join(missing))
        return False

    message = EmailMessage()
    message["Subject"] = _subject(lead)
    message["From"] = settings.email_from
    message["To"] = ", ".join(settings.email_recipients)
    message.set_content(_body(lead))

    try:
        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        return True
    except Exception as exc:
        logger.exception("Email notification failed: %s", exc)
        return False


def _missing_settings(settings) -> list[str]:
    missing = []
    for name in ["smtp_host", "smtp_username", "smtp_password", "email_from"]:
        if not getattr(settings, name):
            missing.append(name.upper())
    if not settings.email_recipients:
        missing.append("EMAIL_TO")
    return missing


def _subject(lead: dict) -> str:
    subreddit = lead.get("subreddit") or "unknown"
    response_type = (lead.get("response_type") or "lead").replace("_", " ")
    return f"[Reddit Lead] {response_type.title()} opportunity in r/{subreddit}"


def _body(lead: dict) -> str:
    return "\n".join(
        [
            "New Reddit opportunity",
            "",
            f"Post title: {lead.get('title') or 'Untitled'}",
            f"Subreddit: r/{lead.get('subreddit') or 'unknown'}",
            f"Matched keyword: {lead.get('query') or ''}",
            f"Intent score: {float(lead['intent_score']):.2f}",
            f"Product fit: {float(lead.get('product_fit_score') or 0):.2f}",
            f"Response type: {lead.get('response_type') or 'helpful_only'}",
            "",
            "Strategy reason:",
            lead.get("strategy_reason") or lead.get("reason") or "",
            "",
            "Suggested comment:",
            lead.get("comment_text") or "(No draft generated.)",
            "",
            "Reddit URL:",
            lead.get("permalink") or "",
        ]
    )
