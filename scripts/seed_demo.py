"""Insert one synthetic lead so the dashboard can be evaluated without Reddit or an API key."""

from app.db import init_db, save_draft, save_post
from app.campaign import create_campaign_workspace, get_campaign_records, load_campaign


POST = {
    "reddit_id": "threadscout_demo_001",
    "title": "What meeting notes tool works well for a remote startup?",
    "subreddit": "startups",
    "permalink": "https://www.reddit.com/r/startups/",
    "url": "https://www.reddit.com/r/startups/",
    "author": "demo_founder",
    "selftext": "We need reliable summaries and action items. What are people using?",
    "query": '"meeting notes tool"',
    "created_utc": 0,
}

QUALIFICATION = {
    "relevance_score": 0.96,
    "purchase_intent_score": 0.91,
    "product_fit_score": 0.89,
    "urgency_score": 0.64,
    "reachability_score": 0.93,
    "promotion_risk_score": 0.24,
    "market_fit_score": 0.90,
    "positive_signals": [
        "Explicitly asks what tool to use",
        "Describes a concrete remote-team workflow",
        "Needs both summaries and action items",
    ],
    "negative_signals": ["No stated deadline or budget"],
}


if __name__ == "__main__":
    init_db()
    records = get_campaign_records()
    if records:
        campaign_key = records[0].key
    else:
        demo = load_campaign("campaigns/example_saas.yaml")
        campaign_key = create_campaign_workspace(demo.name, campaign=demo).key
    save_post(POST, campaign_key=campaign_key)
    draft_id = save_draft(
        reddit_id=POST["reddit_id"],
        intent_score=0.89,
        reason="The author is actively comparing tools for a supported team workflow.",
        comment_text=(
            "I'd compare transcription accuracy, action-item exports, and how each tool "
            "handles recording consent. A short trial with two real meetings usually "
            "reveals more than the feature lists."
        ),
        response_type="expert_answer",
        should_reply=True,
        should_mention_brand=False,
        strategy_reason="Give a useful evaluation framework before mentioning any product.",
        qualification=QUALIFICATION,
        campaign_key=campaign_key,
    )
    print(f"Created synthetic demo lead #{draft_id}")
