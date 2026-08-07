import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import db
from app.campaign import create_campaign_workspace, get_campaign_records, load_campaign
from app.dashboard import render_dashboard
from app.report import render_report, report_csv


def sample_post() -> dict:
    return {
        "reddit_id": "same-post",
        "title": "Need a CRM recommendation",
        "subreddit": "smallbusiness",
        "permalink": "https://reddit.com/r/smallbusiness/comments/same-post/test",
        "url": "https://reddit.com/r/smallbusiness/comments/same-post/test",
        "author": "buyer",
        "selftext": "We are replacing spreadsheets this month.",
        "query": '"CRM recommendation"',
        "created_utc": 1.0,
    }


class ManagedWorkspaceDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(
            database_path=str(Path(self.tmpdir.name) / "test.sqlite3"),
            campaign_path="campaigns/campaign.yaml",
        )
        self.settings_patch = patch("app.db.get_settings", return_value=self.settings)
        self.settings_patch.start()
        db.init_db()

    def tearDown(self):
        self.settings_patch.stop()
        self.tmpdir.cleanup()

    def test_same_reddit_post_is_isolated_between_campaigns(self):
        for key in ["client-a", "client-b"]:
            db.save_post(sample_post(), campaign_key=key)
            db.save_draft(
                reddit_id="same-post",
                intent_score=0.9,
                reason="Clear buying intent",
                comment_text="Compare fit and migration effort.",
                campaign_key=key,
            )

        self.assertEqual(len(db.list_leads(campaign_key="client-a")), 1)
        self.assertEqual(len(db.list_leads(campaign_key="client-b")), 1)
        self.assertEqual(db.lead_stats("client-a")["posts_seen"], 1)
        self.assertTrue(db.has_seen_post("same-post", "client-a"))
        self.assertTrue(db.has_seen_post("same-post", "client-b"))

    def test_review_assignment_outcome_and_value_are_tracked(self):
        db.save_post(sample_post(), campaign_key="client-a")
        draft_id = db.save_draft(
            reddit_id="same-post",
            intent_score=0.9,
            reason="Clear buying intent",
            comment_text="Compare fit and migration effort.",
            campaign_key="client-a",
        )
        db.mark_draft_status(draft_id, "approved", assignee="Maya")
        db.mark_draft_status(
            draft_id,
            "replied",
            final_comment="Published reply",
            outcome="converted",
            conversion_value=1200,
        )
        lead = dict(db.list_leads(campaign_key="client-a")[0])
        stats = db.lead_stats("client-a")

        self.assertEqual(lead["assignee"], "Maya")
        self.assertEqual(lead["outcome"], "converted")
        self.assertEqual(lead["conversion_value"], 1200)
        self.assertEqual(stats["by_status"]["replied"], 1)
        self.assertEqual(stats["conversion_value"], 1200)

    def test_historical_lead_can_be_moved_to_another_campaign(self):
        db.save_post(sample_post(), campaign_key="legacy")
        draft_id = db.save_draft(
            reddit_id="same-post",
            intent_score=0.9,
            reason="Clear buying intent",
            comment_text="Compare fit and migration effort.",
            campaign_key="legacy",
        )
        db.move_draft_to_campaign(draft_id, "salesforce")

        self.assertEqual(len(db.list_leads(campaign_key="legacy")), 0)
        self.assertEqual(len(db.list_leads(campaign_key="salesforce")), 1)
        self.assertEqual(db.lead_stats("legacy")["posts_seen"], 0)
        self.assertEqual(db.lead_stats("salesforce")["posts_seen"], 1)


class ManagedWorkspacePresentationTest(unittest.TestCase):
    def test_creating_workspace_campaign_persists_an_isolated_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "campaigns"
            workspace = root / "workspace.yaml"
            with patch("app.campaign.CAMPAIGNS_ROOT", root), patch(
                "app.campaign.WORKSPACE_PATH", workspace
            ), patch(
                "app.campaign.get_settings",
                return_value=SimpleNamespace(configured_campaign_paths=[]),
            ):
                record = create_campaign_workspace("Salesforce CRM Buyer Intent")
                records = get_campaign_records()

            self.assertEqual(record.key, "salesforce-crm-buyer-intent")
            self.assertTrue(record.path.exists())
            self.assertEqual([item.key for item in records], [record.key])
            self.assertTrue(workspace.exists())

    def test_dashboard_contains_approval_assignment_and_report_workflow(self):
        campaign = load_campaign("campaigns/example_saas.yaml")
        html = render_dashboard(
            [],
            {"posts_seen": 0, "leads_total": 0, "by_status": {}},
            campaign=campaign,
            campaign_key="client-a",
            campaigns=[],
        )
        self.assertIn("Approved to publish", html)
        self.assertIn("trackOutcome", html)
        self.assertIn("+ New", html)
        self.assertIn("/report?campaign=client-a", html)

    def test_report_and_csv_include_revenue_pipeline_fields(self):
        campaign = load_campaign("campaigns/example_saas.yaml")
        leads = [
            {
                "campaign_key": "client-a",
                "status": "replied",
                "outcome": "converted",
                "conversion_value": 500,
                "intent_score": 0.9,
                "subreddit": "SaaS",
                "title": "Need a tool",
                "permalink": "https://reddit.com/example",
            }
        ]
        stats = {
            "posts_seen": 3,
            "leads_total": 1,
            "by_status": {"replied": 1},
            "by_outcome": {"converted": 1},
            "conversion_value": 500,
            "qualified_rate": 1,
        }
        html = render_report(campaign, "client-a", stats, leads, [])
        csv_text = report_csv(leads)
        self.assertIn("Tracked value", html)
        self.assertIn("$500", html)
        self.assertIn("conversion_value", csv_text)
        self.assertIn("converted", csv_text)

    def test_csv_export_neutralizes_spreadsheet_formulas(self):
        csv_text = report_csv([{"title": "=HYPERLINK(\"bad\")"}])
        self.assertIn("'=HYPERLINK", csv_text)

    def test_campaign_registry_loads_multiple_explicit_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "client-a.yaml"
            second = Path(tmp) / "client-b.yaml"
            payload = Path("campaigns/example_saas.yaml").read_text(encoding="utf-8")
            first.write_text(payload, encoding="utf-8")
            second.write_text(payload.replace("AI Meeting Notes", "Second Campaign", 1), encoding="utf-8")
            settings = SimpleNamespace(configured_campaign_paths=[str(first), str(second)])
            with patch("app.campaign.get_settings", return_value=settings):
                records = get_campaign_records()
        self.assertEqual([record.key for record in records], ["client-a", "client-b"])


if __name__ == "__main__":
    unittest.main()
