import json
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.ai import generate_campaign_setup_from_website
from app.campaign import MarketConfig, get_campaign_records
from app.config import Settings
from app.dashboard import render_first_run
from app.main import ProductSetupGenerateRequest, generate_product_setup
from app.website import (
    WebsiteReadError,
    WebsiteResearch,
    _ProductHTMLParser,
    _select_key_links,
    normalize_website_url,
    validate_public_url,
)


def generated_payload() -> dict:
    return {
        "name": "Example CRM Buyer Intent",
        "product": {
            "name": "Example CRM",
            "description": "A CRM for growing sales teams.",
            "value_propositions": ["Pipeline management", "Workflow automation"],
            "limitations": ["Confirm current plan availability"],
            "target_customers": ["Growing B2B sales teams"],
            "competitors": ["Alternative CRM"],
        },
        "market": {
            "countries": [],
            "languages": ["English"],
            "customer_signals": ["sales team", "pipeline"],
            "exclude_terms": ["job posting"],
            "require_market_signal": False,
        },
        "discovery": {
            "keywords": [
                '"Example CRM"',
                "best CRM for B2B sales",
                "CRM alternatives",
                "replace sales spreadsheet",
                "sales pipeline software recommendation",
                "CRM workflow automation",
                "CRM comparison",
                "need a CRM",
            ],
            "subreddits": ["r/sales", "CRM"],
            "excluded_subreddits": ["selfpromotion"],
            "adjacent_subreddits": ["smallbusiness"],
            "watch_only_subreddits": ["marketing"],
            "community_notes": "Verify current subreddit rules before replying.",
            "lookback": "week",
            "sort": "new",
            "limit_per_keyword": 25,
        },
        "qualification": {
            "minimum_lead_score": 0.72,
            "positive_signals": ["Explicitly requests CRM recommendations"],
            "negative_signals": ["Generic news or job post"],
            "max_post_age_days": 7,
        },
        "engagement": {
            "tone": "Helpful, concise, practical, and peer-to-peer.",
            "disclosure": "I work with Example CRM, so I may be biased.",
            "max_words": 140,
        },
        "sample_post": {
            "subreddit": "r/sales",
            "title": "Which CRM works for a growing sales team?",
            "body": "We need pipelines and automation.",
        },
        "review_notes": ["Verify subreddit rules before replying."],
    }


class ProductSetupV05Test(unittest.TestCase):
    def test_fresh_settings_do_not_register_example_campaign(self):
        settings = Settings(_env_file=None)
        self.assertEqual(settings.configured_campaign_paths, [])
        self.assertEqual(MarketConfig().languages, [])
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace.yaml"
            with patch("app.campaign.WORKSPACE_PATH", workspace), patch(
                "app.campaign.get_settings",
                return_value=SimpleNamespace(configured_campaign_paths=[]),
            ):
                self.assertEqual(get_campaign_records(), [])

    def test_first_run_starts_with_website_and_no_demo_product(self):
        html = render_first_run()
        self.assertIn("Generate product setup", html)
        self.assertIn("Nothing is posted automatically", html)
        self.assertNotIn("AI Meeting Notes", html)

    def test_ai_generation_returns_complete_conservative_setup(self):
        with patch("app.ai._chat_json", return_value=json.dumps(generated_payload())):
            result = generate_campaign_setup_from_website(
                "https://example.com",
                "Example CRM helps sales teams manage pipelines.",
            )
        campaign = result["campaign"]
        self.assertEqual(campaign["product"]["website"], "https://example.com")
        self.assertEqual(campaign["discovery"]["subreddits"][0], "sales")
        self.assertEqual(campaign["qualification"]["scoring_mode"], "ai_adaptive")
        self.assertFalse(campaign["engagement"]["allow_brand_mentions"])
        self.assertFalse(campaign["engagement"]["allow_links"])
        self.assertEqual(result["sample_post"]["subreddit"], "sales")

    def test_generate_endpoint_combines_safe_research_and_ai_setup(self):
        research = WebsiteResearch(
            requested_url="https://example.com",
            final_url="https://example.com/product",
            title="Example",
            description="Example product",
            pages=({"url": "https://example.com", "text": "Public product text"},),
        )
        expected = {"campaign": {"name": "Example"}, "sample_post": {}, "review_notes": []}
        with patch("app.main._require_openai_key"), patch(
            "app.main.research_product_website", return_value=research
        ), patch(
            "app.main.generate_campaign_setup_from_website", return_value=expected
        ) as generate:
            result = generate_product_setup(
                ProductSetupGenerateRequest(website_url="example.com", product_notes="B2B")
            )
        self.assertEqual(result["source"]["pages_read"], 1)
        generate.assert_called_once()

    def test_generate_endpoint_turns_website_failure_into_clear_400(self):
        with patch("app.main._require_openai_key"), patch(
            "app.main.research_product_website",
            side_effect=WebsiteReadError("The website could not be reached."),
        ):
            with self.assertRaises(HTTPException) as raised:
                generate_product_setup(ProductSetupGenerateRequest(website_url="example.com"))
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("could not be reached", raised.exception.detail)
        self.assertIn("product description", raised.exception.detail)

    def test_generate_endpoint_can_fall_back_to_operator_notes(self):
        expected = {"campaign": {"name": "Example"}, "sample_post": {}, "review_notes": []}
        with patch("app.main._require_openai_key"), patch(
            "app.main.research_product_website",
            side_effect=WebsiteReadError("The website blocked automated reading."),
        ), patch(
            "app.main.generate_campaign_setup_from_website", return_value=expected
        ) as generate:
            result = generate_product_setup(
                ProductSetupGenerateRequest(
                    website_url="example.com",
                    product_notes="A CRM for growing B2B sales teams.",
                )
            )
        self.assertEqual(result["source"]["pages_read"], 0)
        self.assertIn("blocked", result["source"]["warning"])
        self.assertEqual(generate.call_args.kwargs["website_url"], "https://example.com")


class WebsiteSafetyTest(unittest.TestCase):
    def test_normalizes_domain_without_scheme(self):
        self.assertEqual(normalize_website_url("example.com"), "https://example.com")

    def test_rejects_private_addresses(self):
        with patch(
            "app.website.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
        ):
            with self.assertRaises(WebsiteReadError):
                validate_public_url("https://internal.example")

    def test_accepts_public_address(self):
        with patch(
            "app.website.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
        ):
            self.assertEqual(validate_public_url("example.com"), "https://example.com")

    def test_html_parser_ignores_scripts_and_finds_metadata(self):
        parser = _ProductHTMLParser()
        parser.feed(
            '<html><head><title>Example</title><meta name="description" content="CRM"></head>'
            '<body><script>ignore me</script><h1>Pipeline management</h1>'
            '<a href="/features">Features</a></body></html>'
        )
        self.assertEqual(parser.title, "Example")
        self.assertEqual(parser.description, "CRM")
        self.assertIn("Pipeline management", parser.text)
        self.assertNotIn("ignore me", parser.text)

    def test_key_links_stay_on_same_domain(self):
        links = _select_key_links(
            ["/features", "https://example.com/pricing", "https://other.test/product"],
            "https://example.com",
        )
        self.assertEqual(links, ["https://example.com/features", "https://example.com/pricing"])


if __name__ == "__main__":
    unittest.main()

