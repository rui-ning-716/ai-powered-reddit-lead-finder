import unittest
import time
from types import SimpleNamespace
from unittest.mock import patch

from app import discovery
from app.campaign import load_campaign


def settings(**overrides):
    values = {
        "perplexity_api_key": "pplx-test",
        "perplexity_search_url": "https://api.perplexity.ai/search",
        "perplexity_query_batch_size": 5,
        "perplexity_max_results_per_query": 10,
        "perplexity_timeout_seconds": 30,
        "perplexity_max_retries": 2,
        "apify_api_token": "apify-test",
        "apify_reddit_actor_id": "harshmaur~reddit-scraper",
        "apify_fallback_enabled": True,
        "apify_fallback_min_results": 5,
        "apify_max_results_per_scan": 20,
        "apify_timeout_seconds": 120,
        "discovery_max_queries_per_scan": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def post(reddit_id: str, provider: str = "perplexity") -> dict:
    return {
        "reddit_id": reddit_id,
        "title": f"Post {reddit_id}",
        "subreddit": "SaaS",
        "permalink": f"https://www.reddit.com/r/SaaS/comments/{reddit_id}/post/",
        "url": f"https://www.reddit.com/r/SaaS/comments/{reddit_id}/post/",
        "author": None,
        "selftext": "Need a meeting notes tool",
        "created_utc": None,
        "query": "meeting notes tool",
        "source_provider": provider,
    }


class DiscoveryProviderTest(unittest.TestCase):
    def setUp(self):
        self.campaign = load_campaign("campaigns/campaign.yaml")

    def test_queries_are_bounded_without_subreddit_cartesian_product(self):
        with patch("app.discovery.get_settings", return_value=settings(discovery_max_queries_per_scan=3)):
            queries = discovery.build_search_queries(self.campaign)
        self.assertEqual(len(queries), 3)
        self.assertEqual(queries[0], '"meeting notes tool"')

    def test_generic_queries_are_kept_before_community_variants(self):
        self.campaign.discovery.subreddits = ["SaaS"]
        with patch("app.discovery.get_settings", return_value=settings(discovery_max_queries_per_scan=20)):
            queries = discovery.build_search_queries(self.campaign)
        self.assertEqual(queries[:3], self.campaign.discovery.keywords[:3])
        self.assertTrue(any(" r/" in query for query in queries[3:]))

    def test_perplexity_result_is_normalized_to_existing_post_shape(self):
        result = discovery._normalize_perplexity_post(
            {
                "title": "Need a meeting transcription app",
                "url": "https://www.reddit.com/r/SaaS/comments/abc123/need_an_app/",
                "snippet": "We are replacing our current tool.",
                "date": "2026-08-12",
            },
            ["meeting transcription app"],
        )
        self.assertEqual(result["reddit_id"], "abc123")
        self.assertEqual(result["subreddit"], "SaaS")
        self.assertEqual(result["source_provider"], "perplexity")
        self.assertGreater(result["created_utc"], 0)

    def test_perplexity_accepts_post_url_without_trailing_slash(self):
        result = discovery._normalize_perplexity_post(
            {
                "title": "Salesforce alternatives",
                "url": "https://old.reddit.com/r/sales/comments/abc999/salesforce-alternatives?utm_source=search",
                "snippet": "What are teams using instead?",
            },
            ["Salesforce alternatives"],
        )
        self.assertEqual(result["reddit_id"], "abc999")
        self.assertEqual(result["subreddit"], "sales")

    def test_perplexity_uses_fullname_when_url_has_no_id(self):
        result = discovery._normalize_perplexity_post(
            {
                "id": "t3_abc555",
                "url": "https://www.reddit.com/r/sales/comments/abc555",
                "title": "CRM recommendations",
            },
            ["CRM recommendations"],
        )
        self.assertEqual(result["reddit_id"], "abc555")

    def test_perplexity_search_sends_single_query_strings(self):
        responses = [
            {"results": [{
                "title": "CRM recommendations",
                "url": "https://www.reddit.com/r/sales/comments/abc111/crm/",
                "snippet": "Looking for a CRM",
            }]},
            {"results": [{
                "title": "Sales automation",
                "url": "https://www.reddit.com/r/sales/comments/abc222/automation/",
                "snippet": "Comparing tools",
            }]},
        ]
        with patch("app.discovery.get_settings", return_value=settings(perplexity_query_batch_size=5)), patch(
            "app.discovery._request_json", side_effect=responses
        ) as request:
            result = discovery._search_perplexity(["CRM", "sales automation"], self.campaign)
        self.assertEqual(len(result), 2)
        self.assertEqual([call.kwargs["payload"]["query"] for call in request.call_args_list], ["CRM", "sales automation"])

    def test_apify_result_uses_full_body_and_parsed_id(self):
        result = discovery._normalize_apify_post(
            {
                "dataType": "post",
                "id": "t3_xyz789",
                "parsedId": "xyz789",
                "postUrl": "https://www.reddit.com/r/productivity/comments/xyz789/tool/",
                "title": "Which tool should I buy?",
                "body": "I need action-item extraction.",
                "subredditName": "productivity",
                "authorName": "buyer",
                "createdAt": "2026-08-12T12:00:00.000Z",
                "searchTerm": "meeting action items",
            }
        )
        self.assertEqual(result["reddit_id"], "xyz789")
        self.assertEqual(result["selftext"], "I need action-item extraction.")
        self.assertEqual(result["author"], "buyer")

    def test_apify_is_triggered_only_when_primary_results_are_below_threshold(self):
        with patch("app.discovery.get_settings", return_value=settings()), patch(
            "app.discovery._search_perplexity", return_value=[post("one")]
        ), patch(
            "app.discovery._search_apify", return_value=[post("two", "apify")]
        ) as apify:
            results = discovery.search_posts(self.campaign)
        self.assertEqual({item["reddit_id"] for item in results}, {"one", "two"})
        self.assertTrue(discovery.get_discovery_stats()["apify_triggered"])
        apify.assert_called_once()

    def test_apify_is_not_called_when_perplexity_meets_threshold(self):
        primary = [post(str(index)) for index in range(5)]
        with patch("app.discovery.get_settings", return_value=settings()), patch(
            "app.discovery._search_perplexity", return_value=primary
        ), patch("app.discovery._search_apify") as apify:
            results = discovery.search_posts(self.campaign)
        self.assertEqual(len(results), 5)
        self.assertFalse(discovery.get_discovery_stats()["apify_triggered"])
        apify.assert_not_called()

    def test_age_filter_remains_strict_for_recent_opportunities(self):
        old = post("old-date")
        old["created_utc"] = 1.0
        with patch("app.discovery.get_settings", return_value=settings(apify_api_token="", apify_fallback_enabled=False)), patch(
            "app.discovery._search_perplexity", return_value=[old]
        ):
            results = discovery.search_posts(self.campaign)
        self.assertEqual(len(results), 0)
        self.assertEqual(discovery.get_discovery_stats()["results_rejected_age"], 1)

    def test_week_lookback_is_stricter_than_broader_max_post_age(self):
        self.campaign.discovery.lookback = "week"
        self.campaign.qualification.max_post_age_days = 60
        candidate = post("eight-days")
        candidate["created_utc"] = time.time() - (8 * 24 * 60 * 60)
        with patch("app.discovery.get_settings", return_value=settings(apify_api_token="", apify_fallback_enabled=False)), patch(
            "app.discovery._search_perplexity", return_value=[candidate]
        ):
            results = discovery.search_posts(self.campaign)
        self.assertEqual(results, [])

    def test_market_signals_do_not_require_verbatim_phrase_before_ai(self):
        self.campaign.market.customer_signals = ["Looking for sales automation software"]
        candidate = post("semantic-fit")
        candidate["selftext"] = "Our team is comparing CRM platforms and needs better forecasting."
        with patch("app.discovery.get_settings", return_value=settings(apify_api_token="", apify_fallback_enabled=False)), patch(
            "app.discovery._search_perplexity", return_value=[candidate]
        ):
            results = discovery.search_posts(self.campaign)
        self.assertEqual(len(results), 1)

    def test_excluded_term_is_semantic_evidence_not_a_hard_substring_filter(self):
        self.campaign.market.exclude_terms = ["free CRM"]
        candidate = post("upgrade-from-free")
        candidate["selftext"] = "We outgrew our free CRM and need a paid replacement with automation."
        with patch("app.discovery.get_settings", return_value=settings(apify_api_token="", apify_fallback_enabled=False)), patch(
            "app.discovery._search_perplexity", return_value=[candidate]
        ):
            results = discovery.search_posts(self.campaign)
        self.assertEqual(len(results), 1)
        self.assertEqual(discovery.get_discovery_stats()["results_rejected_excluded_term"], 0)

    def test_high_intent_migration_post_is_ranked_before_generic_mention(self):
        generic = post("generic")
        generic["selftext"] = "A general discussion about CRM history."
        buyer = post("buyer")
        buyer["selftext"] = "We need to replace HubSpot and are comparing Salesforce pricing."
        ranked = discovery._rank_discovered_posts([generic, buyer], self.campaign)
        self.assertEqual(ranked[0]["reddit_id"], "buyer")

    def test_high_intent_words_in_matched_query_do_not_promote_unrelated_post(self):
        unrelated = post("query-noise")
        unrelated["title"] = "Weekly industry news"
        unrelated["selftext"] = "A generic market roundup."
        unrelated["query"] = "CRM alternatives switch pricing"
        buyer = post("real-buyer")
        buyer["title"] = "Which CRM should we replace HubSpot with?"
        buyer["selftext"] = "Our sales team needs automation and forecasting."
        buyer["query"] = "CRM"
        ranked = discovery._rank_discovered_posts([unrelated, buyer], self.campaign)
        self.assertEqual(ranked[0]["reddit_id"], "real-buyer")

    def test_missing_operator_credentials_returns_configuration_error(self):
        empty = settings(perplexity_api_key="", apify_api_token="")
        with patch("app.discovery.get_settings", return_value=empty):
            with self.assertRaises(discovery.DiscoveryConfigurationError):
                discovery.search_posts(self.campaign)


if __name__ == "__main__":
    unittest.main()
