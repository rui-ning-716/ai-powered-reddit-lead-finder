import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.campaign import load_campaign, save_campaign
from app.campaign_ui import render_campaign_wizard
from app.dashboard import render_dashboard
from app.dedupe import find_duplicate_post
from app.scanner import _run_scan_unlocked, run_when_scan_idle, _SCAN_LOCK


def post(**overrides):
    data = {
        "reddit_id": "p1", "title": "Need a meeting notes tool",
        "selftext": "What works well for a remote startup?", "subreddit": "startups",
        "author": "founder", "created_utc": 1000.0,
        "permalink": "https://reddit.com/r/startups/comments/p1/test",
        "url": "https://reddit.com/r/startups/comments/p1/test", "query": '"meeting notes tool"',
    }
    data.update(overrides)
    return data


class CampaignTest(unittest.TestCase):
    def test_example_campaign_loads(self):
        campaign = load_campaign("campaigns/example_saas.yaml")
        self.assertEqual(campaign.product.name, "ExampleNotes")
        self.assertGreaterEqual(len(campaign.discovery.keywords), 3)

    def test_empty_keywords_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.yaml"
            path.write_text("name: x\nproduct: {name: x, description: x}\ndiscovery: {keywords: []}\n")
            with self.assertRaises(ValueError):
                load_campaign(path)

    def test_campaign_can_be_validated_and_atomically_saved(self):
        source = load_campaign("campaigns/example_saas.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "saved.yaml"
            saved = save_campaign(source, target, allowed_root=tmp)
            loaded = load_campaign(target)
        self.assertEqual(saved.product.name, loaded.product.name)
        self.assertEqual(loaded.discovery.keywords, source.discovery.keywords)

    def test_campaign_save_rejects_path_outside_allowed_root(self):
        source = load_campaign("campaigns/example_saas.yaml")
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ValueError):
                save_campaign(source, Path(outside) / "bad.yaml", allowed_root=tmp)

    def test_frontend_contains_all_setup_steps(self):
        html = render_campaign_wizard()
        for label in ["Product", "Market", "Discovery", "Qualification", "Engagement", "Review & Test"]:
            self.assertIn(label, html)
        self.assertIn("/api/campaign/test", html)
        self.assertIn("Save and run scan", html)

    def test_dashboard_shows_post_excerpt_and_localizes_timestamp(self):
        lead = {
            "id": 1, "status": "new", "response_type": "expert_answer",
            "subreddit": "startups", "intent_score": 0.8,
            "should_mention_brand": False, "title": "Need a CRM",
            "permalink": "https://reddit.com/example", "query": '"CRM"',
            "created_at": "2026-08-05T22:44:00+00:00",
            "selftext": "We need Outlook integration and email tracking.",
            "comment_text": "Compare the integrations.",
        }
        html = render_dashboard([lead], {"posts_seen": 1, "leads_total": 1})
        self.assertIn("Original post:", html)
        self.assertIn("We need Outlook integration", html)
        self.assertIn('class="local-time"', html)
        self.assertIn("toLocaleString", html)


class DedupeTest(unittest.TestCase):
    def test_cross_post_is_deduplicated(self):
        first = post(reddit_id="a", subreddit="startups")
        second = post(reddit_id="b", subreddit="SaaS")
        self.assertTrue(find_duplicate_post(second, [first]).is_duplicate)


class ScannerTest(unittest.TestCase):
    def test_campaign_update_guard_rejects_active_scan(self):
        self.assertTrue(_SCAN_LOCK.acquire(blocking=False))
        try:
            accepted, result = run_when_scan_idle(lambda: "saved")
        finally:
            _SCAN_LOCK.release()
        self.assertFalse(accepted)
        self.assertIsNone(result)

    def test_unqualified_post_never_notifies(self):
        settings = SimpleNamespace(max_ai_posts_per_scan=8)
        qualification = {
            "is_qualified": False, "lead_score": 0.2, "market_fit": True,
            "skip_reason": "job listing", "reason": "No buying intent",
        }
        with patch("app.scanner.get_settings", return_value=settings), patch(
            "app.scanner.search_posts", return_value=[post()]
        ), patch("app.scanner.has_seen_post", return_value=False), patch(
            "app.scanner.save_post"
        ), patch("app.scanner.evaluate_opportunity", return_value=qualification), patch(
            "app.scanner.notify_new_lead"
        ) as notify, patch("app.scanner.get_fetch_stats", return_value={}):
            result = _run_scan_unlocked()
        self.assertEqual(result["qualification_skips"], 1)
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
