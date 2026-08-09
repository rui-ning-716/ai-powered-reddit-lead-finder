import json
import logging
import re
from difflib import SequenceMatcher

from openai import OpenAI

from app.campaign import Campaign, get_campaign
from app.config import get_settings

logger = logging.getLogger(__name__)

RESPONSE_TYPES = {
    "helpful_only",
    "expert_answer",
    "soft_mention",
    "direct_recommendation",
    "skip",
}

QUALIFICATION_SCHEMA = {
    "name": "reddit_lead_qualification",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_qualified": {"type": "boolean"},
            "lead_score": {"type": "number", "minimum": 0, "maximum": 1},
            "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
            "purchase_intent_score": {"type": "number", "minimum": 0, "maximum": 1},
            "product_fit_score": {"type": "number", "minimum": 0, "maximum": 1},
            "urgency_score": {"type": "number", "minimum": 0, "maximum": 1},
            "reachability_score": {"type": "number", "minimum": 0, "maximum": 1},
            "promotion_risk_score": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
            "market_fit": {"type": "boolean"},
            "market_fit_score": {"type": "number", "minimum": 0, "maximum": 1},
            "location": {"type": "string"},
            "customer_type": {"type": "string"},
            "inferred_intent": {"type": "string"},
            "urgency": {"type": "string"},
            "positive_signals": {"type": "array", "items": {"type": "string"}},
            "negative_signals": {"type": "array", "items": {"type": "string"}},
            "skip_reason": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": [
            "is_qualified", "lead_score", "relevance_score",
            "purchase_intent_score", "product_fit_score", "urgency_score",
            "reachability_score", "promotion_risk_score", "evidence_confidence_score", "market_fit",
            "market_fit_score", "location", "customer_type", "inferred_intent",
            "urgency", "positive_signals", "negative_signals", "skip_reason", "reason",
        ],
    },
}

STRATEGY_SCHEMA = {
    "name": "reddit_response_strategy",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "response_type": {"type": "string", "enum": sorted(RESPONSE_TYPES)},
            "should_reply": {"type": "boolean"},
            "should_mention_brand": {"type": "boolean"},
            "should_include_link": {"type": "boolean"},
            "reason": {"type": "string"},
            "tone": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "response_type", "should_reply", "should_mention_brand",
            "should_include_link", "reason", "tone", "key_points",
        ],
    },
}

COMMENT_SCHEMA = {
    "name": "reddit_comment_draft",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "comment_text": {"type": "string"},
            "opening_sentence": {"type": "string"},
        },
        "required": ["comment_text", "opening_sentence"],
    },
}

CAMPAIGN_SUGGESTION_SCHEMA = {
    "name": "campaign_discovery_suggestions",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "keywords": {"type": "array", "items": {"type": "string"}},
            "subreddits": {"type": "array", "items": {"type": "string"}},
            "adjacent_subreddits": {"type": "array", "items": {"type": "string"}},
            "watch_only_subreddits": {"type": "array", "items": {"type": "string"}},
            "positive_signals": {"type": "array", "items": {"type": "string"}},
            "negative_signals": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "keywords", "subreddits", "adjacent_subreddits",
            "watch_only_subreddits", "positive_signals", "negative_signals"
        ],
    },
}

CAMPAIGN_SETUP_SCHEMA = {
    "name": "product_website_campaign_setup",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "product": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "value_propositions": {"type": "array", "items": {"type": "string"}},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                    "target_customers": {"type": "array", "items": {"type": "string"}},
                    "competitors": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name", "description", "value_propositions", "limitations",
                    "target_customers", "competitors",
                ],
            },
            "market": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "countries": {"type": "array", "items": {"type": "string"}},
                    "languages": {"type": "array", "items": {"type": "string"}},
                    "customer_signals": {"type": "array", "items": {"type": "string"}},
                    "exclude_terms": {"type": "array", "items": {"type": "string"}},
                    "require_market_signal": {"type": "boolean"},
                },
                "required": [
                    "countries", "languages", "customer_signals",
                    "exclude_terms", "require_market_signal",
                ],
            },
            "discovery": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "subreddits": {"type": "array", "items": {"type": "string"}},
                    "excluded_subreddits": {"type": "array", "items": {"type": "string"}},
                    "adjacent_subreddits": {"type": "array", "items": {"type": "string"}},
                    "watch_only_subreddits": {"type": "array", "items": {"type": "string"}},
                    "community_notes": {"type": "string"},
                    "lookback": {"type": "string", "enum": ["day", "week", "month", "year"]},
                    "sort": {"type": "string", "enum": ["new", "relevance", "top"]},
                    "limit_per_keyword": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": [
                    "keywords", "subreddits", "excluded_subreddits",
                    "adjacent_subreddits", "watch_only_subreddits", "community_notes",
                    "lookback", "sort", "limit_per_keyword",
                ],
            },
            "qualification": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "minimum_lead_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "positive_signals": {"type": "array", "items": {"type": "string"}},
                    "negative_signals": {"type": "array", "items": {"type": "string"}},
                    "max_post_age_days": {"type": "integer", "minimum": 1, "maximum": 365},
                },
                "required": [
                    "minimum_lead_score", "positive_signals", "negative_signals",
                    "max_post_age_days",
                ],
            },
            "engagement": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tone": {"type": "string"},
                    "disclosure": {"type": "string"},
                    "max_words": {"type": "integer", "minimum": 30, "maximum": 400},
                },
                "required": ["tone", "disclosure", "max_words"],
            },
            "sample_post": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subreddit": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["subreddit", "title", "body"],
            },
            "review_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "name", "product", "market", "discovery", "qualification",
            "engagement", "sample_post", "review_notes",
        ],
    },
}

QUALIFICATION_PROMPT = """
Evaluate whether this Reddit post is a real, reachable lead for the configured product.

Score each dimension independently:
- relevance: how closely the post matches the problem the product solves
- purchase intent: evidence the author is seeking, comparing, replacing, or paying for a solution
- product fit: whether the configured product can genuinely solve the stated need
- urgency: evidence the problem needs to be solved soon
- reachability: whether one public Reddit reply could usefully move the conversation forward
- promotion risk: likelihood that a brand response would feel intrusive, irrelevant, or spammy
- market fit: whether the author matches supported geography, language, and customer profile

Do not confuse a keyword mention with buying intent. Job listings, news, tutorials,
promotional posts, generic discussion, solved problems, and incidental mentions should
normally receive low purchase-intent scores. Use only evidence in the post and campaign.
Do not invent location, budget, company size, deadlines, or product capabilities.

For AI adaptive scoring, infer the product-specific sub-signals internally from
the campaign and the post. Do not expose those sub-signals to the user. Return
an evidence_confidence_score based on how explicit, complete, and internally
consistent the evidence in the post is. The application will deterministically
calculate the final priority after your assessment, so return honest independent
component scores rather than trying to game a total.
""".strip()

STRATEGY_PROMPT = """
Choose the safest useful response strategy for a qualified Reddit opportunity.

helpful_only: answer the question without mentioning the product.
expert_answer: give domain-specific guidance without mentioning the product.
soft_mention: help first, then briefly mention the product with transparent affiliation.
direct_recommendation: use only when the author explicitly asks for recommendations and
the product strongly fits. Disclose affiliation.
skip: use when a reply would be intrusive, promotional, low-value, or against the campaign rules.

Default to no brand mention. Never recommend a link unless campaign settings allow it and
the author explicitly requests resources or links. A public reply must not pretend to be an
independent customer or hide the responder's affiliation.
""".strip()

COMMENT_PROMPT = """
Write a concise Reddit reply using the selected strategy and campaign constraints.
Answer the specific question first. Sound like a knowledgeable participant, not an ad or a
customer-support script. Never fabricate personal experience, customer results, policies,
prices, availability, or product capabilities. Never claim to have used the product unless
the source explicitly says so. When the author asks for recommendations or comparisons,
name 2 to 4 relevant options and explain one practical tradeoff for each instead of returning
only a generic checklist. Do not name the campaign product when brand mentions are disabled,
but neutral alternatives may be named when they are factually supported. Qualify claims that
may change, such as pricing, plan limits, and integrations, and suggest verifying current
details. If mentioning the campaign product, use transparent affiliation, include the campaign
disclosure, and keep the mention secondary to useful information. Do not include a link unless
the strategy explicitly allows it. Return an empty comment for skip.
""".strip()


URGENCY_PATTERNS = (
    r"\b(?:asap|urgent|urgently|deadline|time[- ]sensitive)\b",
    r"\b(?:today|tomorrow|tonight|this week|next week|this month|next month)\b",
    r"\bwithin\s+(?:the\s+next\s+)?\d+\s+(?:hours?|days?|weeks?)\b",
    r"\b(?:by|before)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\b(?:by|before)\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    r"\b(?:renewal|contract)\s+(?:is\s+)?(?:due|expires?|ends?)\b",
)


def evaluate_opportunity(post: dict, campaign: Campaign | None = None) -> dict:
    campaign = campaign or get_campaign()
    content = _chat_json(
        schema=QUALIFICATION_SCHEMA,
        system_prompt=QUALIFICATION_PROMPT,
        user_prompt=f"Campaign:\n{_campaign_context(campaign)}\n\nPost:\n{_post_context(post)}",
        temperature=0.2,
    )
    return validate_qualification(json.loads(content), campaign, post)


def validate_qualification(
    payload: dict,
    campaign: Campaign | None = None,
    post: dict | None = None,
) -> dict:
    campaign = campaign or get_campaign()
    score_fields = [
        "relevance_score", "purchase_intent_score", "product_fit_score",
        "urgency_score", "reachability_score", "promotion_risk_score", "evidence_confidence_score", "market_fit_score",
    ]
    result = dict(payload)
    # Preserve deterministic results for legacy payloads created before adaptive confidence.
    if "evidence_confidence_score" not in result:
        result["evidence_confidence_score"] = 1.0
    for field in score_fields:
        result[field] = max(0.0, min(1.0, float(result.get(field) or 0)))
    if post is not None and not _has_explicit_urgency(post):
        result["urgency_score"] = min(result["urgency_score"], 0.6)
    score_model = campaign.qualification.score_model
    weights = score_model.weights.normalized()
    positive_score = sum(
        weights[name] * result[f"{name}_score"] for name in weights
    )
    promotion_risk_deduction = (
        score_model.promotion_risk_penalty / 100
    ) * result["promotion_risk_score"]
    market_mismatch_deduction = (
        score_model.market_mismatch_penalty / 100
    ) * (1.0 - result["market_fit_score"])
    confidence = result["evidence_confidence_score"] if campaign.qualification.scoring_mode == "ai_adaptive" else 1.0
    weighted_score = (
        positive_score * confidence - promotion_risk_deduction - market_mismatch_deduction
    )
    result["lead_score"] = round(max(0.0, min(1.0, weighted_score)), 3)
    result["score_breakdown"] = {
        "normalized_weights": {name: round(value, 4) for name, value in weights.items()},
        "positive_score": round(positive_score, 4),
        "evidence_confidence": round(confidence, 4),
        "promotion_risk_deduction": round(promotion_risk_deduction, 4),
        "market_mismatch_deduction": round(market_mismatch_deduction, 4),
    }
    threshold = campaign.qualification.minimum_lead_score
    result["is_qualified"] = bool(
        result.get("is_qualified")
        and result.get("market_fit")
        and result["lead_score"] >= threshold
    )
    result["positive_signals"] = [str(x) for x in result.get("positive_signals", [])][:8]
    result["negative_signals"] = [str(x) for x in result.get("negative_signals", [])][:8]
    return result


def decide_response_strategy(
    post: dict, qualification: dict, campaign: Campaign | None = None
) -> dict:
    campaign = campaign or get_campaign()
    try:
        content = _chat_json(
            schema=STRATEGY_SCHEMA,
            system_prompt=STRATEGY_PROMPT,
            user_prompt=(
                f"Campaign:\n{_campaign_context(campaign)}\n\nPost:\n{_post_context(post)}"
                f"\n\nQualification:\n{json.dumps(qualification, indent=2)}"
            ),
            temperature=0.2,
        )
        return validate_strategy(json.loads(content), campaign)
    except Exception as exc:
        logger.warning("strategy selection failed; using conservative fallback: %s", exc)
        return conservative_strategy()


def validate_strategy(payload: dict, campaign: Campaign | None = None) -> dict:
    campaign = campaign or get_campaign()
    response_type = payload.get("response_type")
    if response_type not in RESPONSE_TYPES:
        raise ValueError(f"Invalid response_type: {response_type}")
    should_reply = bool(payload.get("should_reply")) and response_type != "skip"
    should_mention = bool(payload.get("should_mention_brand"))
    should_include_link = bool(payload.get("should_include_link"))
    if response_type in {"helpful_only", "expert_answer", "skip"}:
        should_mention = False
        should_include_link = False
    should_mention = should_mention and campaign.engagement.allow_brand_mentions
    reason = str(payload.get("reason") or "")
    if response_type in {"soft_mention", "direct_recommendation"} and not should_mention:
        response_type = "expert_answer"
        should_include_link = False
        reason = (
            "Brand mentions are disabled or were not approved for this reply. "
            "Provide a neutral expert answer focused on the author's requirements "
            "and concrete alternatives."
        )
    should_include_link = (
        should_include_link
        and should_mention
        and campaign.engagement.allow_links
    )
    return {
        "response_type": response_type,
        "should_reply": should_reply,
        "should_mention_brand": should_mention,
        "should_include_link": should_include_link,
        "reason": reason,
        "tone": str(payload.get("tone") or campaign.engagement.tone),
        "key_points": [str(item) for item in payload.get("key_points", [])][:6],
    }


def conservative_strategy() -> dict:
    return {
        "response_type": "helpful_only",
        "should_reply": True,
        "should_mention_brand": False,
        "should_include_link": False,
        "reason": "Fallback: help without mentioning a product.",
        "tone": "helpful and concise",
        "key_points": ["Answer the question directly", "Avoid promotional wording"],
    }


def generate_personalized_comment(
    post: dict,
    qualification: dict,
    strategy: dict,
    recent_comments: list[str] | None = None,
    campaign: Campaign | None = None,
) -> dict:
    if not strategy.get("should_reply") or strategy.get("response_type") == "skip":
        return {"comment_text": "", "opening_sentence": ""}
    recent_comments = recent_comments or []
    campaign = campaign or get_campaign()
    draft = _generate_comment_once(post, qualification, strategy, recent_comments, campaign)
    if is_opening_too_similar(draft.get("opening_sentence", ""), recent_comments):
        draft = _generate_comment_once(post, qualification, strategy, recent_comments, campaign)
    return draft


def _generate_comment_once(post, qualification, strategy, recent_comments, campaign) -> dict:
    prompt = (
        f"Campaign:\n{_campaign_context(campaign)}\n\nPost:\n{_post_context(post)}"
        f"\n\nQualification:\n{json.dumps(qualification, indent=2)}"
        f"\n\nStrategy:\n{json.dumps(strategy, indent=2)}"
        f"\n\nRecent openings to avoid:\n{json.dumps([extract_opening_sentence(x) for x in recent_comments[:20]])}"
        f"\n\nMaximum words: {campaign.engagement.max_words}"
    )
    draft = json.loads(_chat_json(COMMENT_SCHEMA, COMMENT_PROMPT, prompt, 0.65))
    draft["comment_text"] = validate_comment_for_strategy(
        draft.get("comment_text", ""), strategy, campaign
    )
    return draft


def suggest_campaign_discovery(campaign: Campaign) -> dict:
    prompt = """
Suggest a compact Reddit discovery setup for this campaign. Return 6 to 10
search queries covering direct need, pain points, competitor alternatives, and
product comparisons. Put exact multi-word searches in double quotes. Suggest
3 to 8 core subreddit names without the r/ prefix, plus compact adjacent and
watch-only community lists. Core communities should be appropriate for active
opportunity monitoring. Watch-only communities may be useful for research but
carry higher promotion risk. Positive and negative signals must help
distinguish genuine solution-seeking from keyword mentions.
Do not invent product capabilities or supported markets.
""".strip()
    content = _chat_json(
        CAMPAIGN_SUGGESTION_SCHEMA,
        prompt,
        _campaign_context(campaign),
        0.35,
    )
    result = json.loads(content)
    return {
        "keywords": [str(x) for x in result.get("keywords", [])][:12],
        "subreddits": [str(x).removeprefix("r/") for x in result.get("subreddits", [])][:10],
        "adjacent_subreddits": [
            str(x).removeprefix("r/") for x in result.get("adjacent_subreddits", [])
        ][:10],
        "watch_only_subreddits": [
            str(x).removeprefix("r/") for x in result.get("watch_only_subreddits", [])
        ][:10],
        "positive_signals": [str(x) for x in result.get("positive_signals", [])][:10],
        "negative_signals": [str(x) for x in result.get("negative_signals", [])][:10],
    }


def generate_campaign_setup_from_website(
    website_url: str,
    website_research: str,
    product_notes: str = "",
) -> dict:
    """Generate a conservative, fully editable product setup from public website text."""
    prompt = """
Create a complete Reddit reply-opportunity setup from the supplied public product website.
This is an editable draft for a human marketing or sales operator, not permission to post.

Product:
- Use only capabilities and positioning supported by the source text.
- Identify concise value propositions, target customers, likely alternatives, and limitations.
- When a limitation or competitor is uncertain, use cautious wording rather than inventing facts.

Market:
- Only name supported countries or regions when the source provides evidence.
- Use an empty country list when geography is unknown or appears global.
- Infer site languages from the supplied text. Do not assume the customer's location.

Discovery:
- Return 8 to 12 diverse Reddit search queries. Reddit search is lexical, not semantic.
- Cover brand, category, recommendation, alternative, comparison, pain-point, and replacement language.
- Use quotes only for exact brand or established multi-word product phrases. Do not quote every query.
- Suggest plausible subreddit names without r/. These are candidates, not verified rule claims.
- Community notes must tell the operator to verify current subreddit rules before replying.

Qualification:
- Define concrete positive buying signals and negative/noise signals for this product.
- Use a balanced default threshold unless the product is unusually sensitive or regulated.

Engagement:
- Write a helpful, concise, peer-to-peer tone instruction.
- Provide a transparent affiliation disclosure template for the product team.
- The application will keep brand mentions and direct links disabled until a human enables them.

Review and test:
- Create one realistic sample Reddit post that should be a plausible qualified opportunity.
- Add concise review notes for uncertain market, product, or community assumptions.

Do not claim that a subreddit allows promotion. Do not fabricate prices, availability, results,
certifications, customer counts, or legal claims.
""".strip()
    notes = product_notes.strip()[:4000]
    user_prompt = (
        f"Website to use in the setup: {website_url}\n\n"
        f"Optional operator notes:\n{notes or '(none)'}\n\n"
        f"Public website research:\n{website_research}"
    )
    raw = json.loads(_chat_json(CAMPAIGN_SETUP_SCHEMA, prompt, user_prompt, 0.25))
    product = raw.get("product") or {}
    market = raw.get("market") or {}
    discovery = raw.get("discovery") or {}
    qualification = raw.get("qualification") or {}
    engagement = raw.get("engagement") or {}
    product_name = str(product.get("name") or "").strip()
    generated_keywords = _clean_generated_list(discovery.get("keywords"), 12)
    if not generated_keywords and product_name:
        generated_keywords = [product_name, f"{product_name} alternatives"]
    payload = {
        "name": str(raw.get("name") or product.get("name") or "Product setup").strip(),
        "product": {
            "name": product_name,
            "description": str(product.get("description") or "").strip(),
            "website": website_url,
            "value_propositions": _clean_generated_list(product.get("value_propositions"), 10),
            "limitations": _clean_generated_list(product.get("limitations"), 10),
            "target_customers": _clean_generated_list(product.get("target_customers"), 10),
            "competitors": _clean_generated_list(product.get("competitors"), 10),
        },
        "market": {
            "countries": _clean_generated_list(market.get("countries"), 15),
            "languages": _clean_generated_list(market.get("languages"), 10),
            "customer_signals": _clean_generated_list(market.get("customer_signals"), 15),
            "exclude_terms": _clean_generated_list(market.get("exclude_terms"), 15),
            "require_market_signal": bool(market.get("require_market_signal")),
        },
        "discovery": {
            "keywords": generated_keywords,
            "subreddits": _clean_subreddits(discovery.get("subreddits"), 10),
            "excluded_subreddits": _clean_subreddits(discovery.get("excluded_subreddits"), 10),
            "adjacent_subreddits": _clean_subreddits(discovery.get("adjacent_subreddits"), 10),
            "watch_only_subreddits": _clean_subreddits(discovery.get("watch_only_subreddits"), 10),
            "community_notes": str(discovery.get("community_notes") or "").strip(),
            "lookback": discovery.get("lookback") or "week",
            "sort": discovery.get("sort") or "new",
            "limit_per_keyword": int(discovery.get("limit_per_keyword") or 25),
        },
        "qualification": {
            "minimum_lead_score": float(qualification.get("minimum_lead_score") or 0.72),
            "positive_signals": _clean_generated_list(qualification.get("positive_signals"), 12),
            "negative_signals": _clean_generated_list(qualification.get("negative_signals"), 12),
            "max_post_age_days": int(qualification.get("max_post_age_days") or 7),
            "scoring_mode": "ai_adaptive",
        },
        "engagement": {
            "allow_brand_mentions": False,
            "allow_links": False,
            "tone": str(engagement.get("tone") or "Helpful, concise, practical, and peer-to-peer.").strip(),
            "disclosure": str(engagement.get("disclosure") or "").strip(),
            "max_words": int(engagement.get("max_words") or 140),
        },
    }
    campaign = Campaign.model_validate(payload)
    sample = raw.get("sample_post") or {}
    return {
        "campaign": campaign.model_dump(mode="json"),
        "sample_post": {
            "subreddit": str(sample.get("subreddit") or "all").removeprefix("r/").strip(),
            "title": str(sample.get("title") or "").strip(),
            "body": str(sample.get("body") or "").strip(),
        },
        "review_notes": _clean_generated_list(raw.get("review_notes"), 10),
    }


def _clean_generated_list(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        cleaned = " ".join(str(item).split()).strip()
        if cleaned and cleaned.casefold() not in {existing.casefold() for existing in result}:
            result.append(cleaned[:500])
        if len(result) >= limit:
            break
    return result


def _clean_subreddits(value, limit: int) -> list[str]:
    return [item.removeprefix("r/").strip(" /") for item in _clean_generated_list(value, limit) if item.strip(" /")]


def validate_comment_for_strategy(
    comment: str, strategy: dict, campaign: Campaign | None = None
) -> str:
    campaign = campaign or get_campaign()
    if not strategy.get("should_reply") or strategy.get("response_type") == "skip":
        return ""
    if not strategy.get("should_mention_brand"):
        comment = _remove_brand_sentences(comment, campaign.product.name)
    if not strategy.get("should_include_link"):
        comment = re.sub(r"https?://\S+", "", comment).strip()
    words = comment.split()
    return " ".join(words[: campaign.engagement.max_words]).strip()


def _remove_brand_sentences(comment: str, brand: str) -> str:
    if not brand or brand.casefold() not in comment.casefold():
        return comment
    parts = re.split(r"(?<=[.!?])\s+", comment.strip())
    return " ".join(part for part in parts if brand.casefold() not in part.casefold()).strip()


def is_opening_too_similar(opening: str, recent_comments: list[str], threshold=0.82) -> bool:
    normalized = _normalize(opening)
    if not normalized:
        return False
    return any(
        previous and SequenceMatcher(None, normalized, previous).ratio() >= threshold
        for previous in (_normalize(extract_opening_sentence(x)) for x in recent_comments)
    )


def extract_opening_sentence(comment: str) -> str:
    match = re.search(r"(.+?[.!?])(?:\s|$)", comment.strip(), re.DOTALL)
    return match.group(1).strip() if match else comment.strip().split("\n", 1)[0]


def _chat_json(schema: dict, system_prompt: str, user_prompt: str, temperature: float) -> str:
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=temperature,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_schema", "json_schema": schema},
    )
    return response.choices[0].message.content or "{}"


def _campaign_context(campaign: Campaign) -> str:
    return campaign.model_dump_json(indent=2)


def _post_context(post: dict) -> str:
    return (
        f"Subreddit: r/{post['subreddit']}\nTitle: {post['title']}\n"
        f"Body:\n{post.get('selftext') or '(empty)'}\nMatched query: {post.get('query') or ''}"
    )


def _has_explicit_urgency(post: dict) -> bool:
    text = f"{post.get('title') or ''}\n{post.get('selftext') or post.get('body') or ''}"
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in URGENCY_PATTERNS)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
