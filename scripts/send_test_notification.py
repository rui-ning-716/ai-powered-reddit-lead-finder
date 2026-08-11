from app.notifications.email import send_email_notification
from app.notifications.slack import send_slack_notification


TEST_LEAD = {
    "intent_score": 0.91,
    "response_type": "soft_mention",
    "purchase_intent_score": 0.88,
    "product_fit_score": 0.90,
    "subreddit": "startups",
    "title": "What meeting notes tool works for a remote team?",
    "strategy_reason": "The author explicitly requests product recommendations.",
    "reason": "Clear problem, supported customer, and active product search.",
    "comment_text": (
        "I'd compare transcription accuracy, action-item exports, and how each "
        "tool handles consent before committing to an annual plan."
    ),
    "permalink": "https://www.reddit.com/r/startups/",
    "query": '"meeting notes tool"',
}


if __name__ == "__main__":
    slack_sent = send_slack_notification(TEST_LEAD)
    email_sent = send_email_notification(TEST_LEAD)
    print({"slack_sent": slack_sent, "email_sent": email_sent})

