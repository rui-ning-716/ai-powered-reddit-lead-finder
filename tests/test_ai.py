import unittest

from app.ai import (
    COMMENT_PROMPT,
    conservative_strategy,
    is_opening_too_similar,
    validate_comment_for_strategy,
    validate_qualification,
    validate_strategy,
    suggest_campaign_discovery,
)
from app.campaign import get_campaign


class AITest(unittest.TestCase):
    def test_multidimensional_qualification_enforces_threshold_and_market(self):
        payload = {
            "is_qualified": True,
            "lead_score": 0.85,
            "relevance_score": 0.9,
            "purchase_intent_score": 0.8,
            "product_fit_score": 0.9,
            "urgency_score": 0.5,
            "reachability_score": 0.9,
            "promotion_risk_score": 0.2,
            "market_fit": True,
            "market_fit_score": 0.9,
            "positive_signals": ["asking for recommendations"],
            "negative_signals": [],
        }
        result = validate_qualification(payload)
        self.assertTrue(result["is_qualified"])
        self.assertEqual(result["purchase_intent_score"], 0.8)

    def test_poor_market_fit_disqualifies_high_score(self):
        payload = {
            "is_qualified": True, "lead_score": 0.95, "market_fit": False,
            "relevance_score": 1, "purchase_intent_score": 1, "product_fit_score": 1,
            "urgency_score": 1, "reachability_score": 1, "promotion_risk_score": 0,
            "market_fit_score": 0, "positive_signals": [], "negative_signals": [],
        }
        self.assertFalse(validate_qualification(payload)["is_qualified"])

    def test_lead_score_is_recalculated_from_dimensions(self):
        payload = {
            "is_qualified": True, "lead_score": 0.99, "market_fit": True,
            "relevance_score": 0.8, "purchase_intent_score": 0.7,
            "product_fit_score": 0.8, "urgency_score": 0.5,
            "reachability_score": 0.9, "promotion_risk_score": 0.2,
            "market_fit_score": 0.9, "positive_signals": [], "negative_signals": [],
        }
        result = validate_qualification(payload)
        self.assertEqual(result["lead_score"], 0.71)

    def test_campaign_score_weights_and_penalties_change_final_score(self):
        campaign = get_campaign().model_copy(deep=True)
        weights = campaign.qualification.score_model.weights
        weights.relevance = 0
        weights.purchase_intent = 0
        weights.product_fit = 100
        weights.urgency = 0
        weights.reachability = 0
        campaign.qualification.score_model.promotion_risk_penalty = 0
        campaign.qualification.score_model.market_mismatch_penalty = 0
        payload = {
            "is_qualified": True, "lead_score": 0.01, "market_fit": True,
            "relevance_score": 0.1, "purchase_intent_score": 0.2,
            "product_fit_score": 0.83, "urgency_score": 0.4,
            "reachability_score": 0.5, "promotion_risk_score": 1,
            "market_fit_score": 0.2, "positive_signals": [], "negative_signals": [],
        }
        result = validate_qualification(payload, campaign=campaign)
        self.assertEqual(result["lead_score"], 0.83)
        self.assertEqual(result["score_breakdown"]["normalized_weights"]["product_fit"], 1.0)

    def test_campaign_score_model_supports_dimension_subsignals(self):
        campaign = get_campaign().model_copy(deep=True)
        signals = campaign.qualification.score_model.dimension_signals
        signals.purchase_intent = ["Pricing page or a stated budget", "Actively comparing vendors"]
        self.assertEqual(
            campaign.model_dump()["qualification"]["score_model"]["dimension_signals"]["purchase_intent"],
            ["Pricing page or a stated budget", "Actively comparing vendors"],
        )

    def test_ai_adaptive_priority_multiplies_positive_score_by_confidence(self):
        campaign = get_campaign().model_copy(deep=True)
        campaign.qualification.scoring_mode = "ai_adaptive"
        campaign.qualification.score_model.promotion_risk_penalty = 0
        campaign.qualification.score_model.market_mismatch_penalty = 0
        payload = {
            "is_qualified": True, "market_fit": True,
            "relevance_score": 1, "purchase_intent_score": 1,
            "product_fit_score": 1, "urgency_score": 1,
            "reachability_score": 1, "promotion_risk_score": 0,
            "market_fit_score": 1, "evidence_confidence_score": 0.6,
            "positive_signals": [], "negative_signals": [],
        }
        result = validate_qualification(payload, campaign=campaign)
        self.assertEqual(result["lead_score"], 0.6)

    def test_urgency_is_capped_without_explicit_time_signal(self):
        payload = {
            "is_qualified": True, "lead_score": 0.99, "market_fit": True,
            "relevance_score": 1, "purchase_intent_score": 1,
            "product_fit_score": 1, "urgency_score": 0.95,
            "reachability_score": 1, "promotion_risk_score": 0,
            "market_fit_score": 1, "positive_signals": [], "negative_signals": [],
        }
        post = {"title": "Looking for a CRM", "selftext": "What do you recommend?"}
        result = validate_qualification(payload, post=post)
        self.assertEqual(result["urgency_score"], 0.6)

    def test_explicit_deadline_preserves_urgency(self):
        payload = {
            "is_qualified": True, "lead_score": 0.99, "market_fit": True,
            "relevance_score": 1, "purchase_intent_score": 1,
            "product_fit_score": 1, "urgency_score": 0.9,
            "reachability_score": 1, "promotion_risk_score": 0,
            "market_fit_score": 1, "positive_signals": [], "negative_signals": [],
        }
        post = {"title": "Need a CRM by Friday", "selftext": "Our contract ends soon."}
        result = validate_qualification(payload, post=post)
        self.assertEqual(result["urgency_score"], 0.9)

    def test_helpful_strategy_cannot_mention_brand_or_link(self):
        strategy = validate_strategy({
            "response_type": "helpful_only", "should_reply": True,
            "should_mention_brand": True, "should_include_link": True,
            "reason": "Help first", "tone": "casual", "key_points": [],
        })
        self.assertFalse(strategy["should_mention_brand"])
        self.assertFalse(strategy["should_include_link"])

    def test_brand_disabled_downgrades_mention_strategy(self):
        campaign = get_campaign().model_copy(deep=True)
        campaign.engagement.allow_brand_mentions = False
        strategy = validate_strategy({
            "response_type": "soft_mention", "should_reply": True,
            "should_mention_brand": True, "should_include_link": True,
            "reason": "The product is relevant", "tone": "helpful", "key_points": [],
        }, campaign)
        self.assertEqual(strategy["response_type"], "expert_answer")
        self.assertFalse(strategy["should_mention_brand"])
        self.assertFalse(strategy["should_include_link"])
        self.assertIn("neutral expert answer", strategy["reason"])

    def test_comment_removes_brand_and_link_when_disallowed(self):
        campaign = get_campaign()
        comment = f"Try a structured template first. {campaign.product.name} can help. https://example.com"
        result = validate_comment_for_strategy(comment, {
            "response_type": "helpful_only", "should_reply": True,
            "should_mention_brand": False, "should_include_link": False,
        })
        self.assertNotIn(campaign.product.name, result)
        self.assertNotIn("https://", result)

    def test_no_fake_experience_rule_is_in_prompt(self):
        self.assertIn("Never fabricate personal experience", COMMENT_PROMPT)
        self.assertIn("transparent affiliation", COMMENT_PROMPT)
        self.assertIn("name 2 to 4 relevant options", COMMENT_PROMPT)

    def test_opening_similarity_detects_duplicate(self):
        recent = ["I'd compare the export formats before switching."]
        self.assertTrue(is_opening_too_similar(recent[0], recent))

    def test_conservative_strategy_never_mentions_brand(self):
        self.assertFalse(conservative_strategy()["should_mention_brand"])

    def test_campaign_suggestions_are_bounded_and_strip_subreddit_prefix(self):
        payload = {
            "keywords": [f'"query {i}"' for i in range(20)],
            "subreddits": ["r/startups", "SaaS"],
            "positive_signals": ["asks for a recommendation"],
            "negative_signals": ["job listing"],
        }
        import json
        from unittest.mock import patch
        with patch("app.ai._chat_json", return_value=json.dumps(payload)):
            result = suggest_campaign_discovery(get_campaign())
        self.assertEqual(len(result["keywords"]), 12)
        self.assertEqual(result["subreddits"][0], "startups")


if __name__ == "__main__":
    unittest.main()
