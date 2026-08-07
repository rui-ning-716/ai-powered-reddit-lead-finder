import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import db
from app.notifications import service


def settings_for(path: Path, **overrides):
    values = {
        "database_path": str(path),
        "slack_notifications_enabled": False,
        "slack_webhook_url": "",
        "slack_min_intent_score": 0.72,
        "email_notifications_enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "email_from": "",
        "email_to": "",
        "email_recipients": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class NotificationTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        self.settings = settings_for(self.db_path)
        self.db_settings = patch("app.db.get_settings", return_value=self.settings)
        self.service_settings = patch("app.notifications.service.get_settings", return_value=self.settings)
        self.db_settings.start()
        self.service_settings.start()
        db.init_db()
        db.save_post(
            {
                "reddit_id": "abc123",
                "title": "Need a meeting notes tool",
                "subreddit": "StudentNurse",
                "permalink": "https://reddit.com/r/StudentNurse/comments/abc123/test",
                "url": "https://reddit.com/r/StudentNurse/comments/abc123/test",
                "author": "user",
                "selftext": "Our remote team needs better action items.",
                "query": '"meeting notes tool"',
                "created_utc": 1.0,
            }
        )

    def tearDown(self):
        self.service_settings.stop()
        self.db_settings.stop()
        self.tmpdir.cleanup()

    def _save_draft(self, **overrides):
        values = {
            "reddit_id": "abc123",
            "intent_score": 0.91,
            "reason": "High intent, US healthcare context.",
            "comment_text": "Compare transcription quality and action item exports.",
            "response_type": "expert_answer",
            "should_reply": True,
            "should_mention_brand": False,
            "should_include_link": False,
            "strategy_reason": "Certification requirement question.",
        }
        values.update(overrides)
        return db.save_draft(**values)

    def test_slack_notification_deduplication(self):
        self.settings.slack_notifications_enabled = True
        self.settings.slack_webhook_url = "https://hooks.slack.test/services/1"
        draft_id = self._save_draft()

        with patch("app.notifications.service.send_slack_notification", return_value=True) as send:
            service.notify_new_lead(draft_id)
            service.notify_new_lead(draft_id)

        self.assertEqual(send.call_count, 1)

    def test_email_notification_deduplication(self):
        self.settings.email_notifications_enabled = True
        self.settings.smtp_host = "smtp.test"
        self.settings.smtp_username = "user"
        self.settings.smtp_password = "pass"
        self.settings.email_from = "from@example.com"
        self.settings.email_recipients = ["one@example.com", "two@example.com"]
        draft_id = self._save_draft()

        with patch("app.notifications.service.send_email_notification", return_value=True) as send:
            service.notify_new_lead(draft_id)
            service.notify_new_lead(draft_id)

        self.assertEqual(send.call_count, 1)

    def test_disabled_notifications_do_not_crash_or_send(self):
        draft_id = self._save_draft()

        with patch("app.notifications.service.send_slack_notification") as slack_send, patch(
            "app.notifications.service.send_email_notification"
        ) as email_send:
            result = service.notify_new_lead(draft_id)

        self.assertEqual(result, {"slack": False, "email": False})
        slack_send.assert_not_called()
        email_send.assert_not_called()

    def test_lead_listing_includes_original_post_body(self):
        self._save_draft()
        lead = dict(db.list_leads()[0])
        self.assertEqual(lead["selftext"], "Our remote team needs better action items.")

    def test_notification_failure_does_not_fail_scan_flow(self):
        self.settings.slack_notifications_enabled = True
        self.settings.slack_webhook_url = "https://hooks.slack.test/services/1"
        draft_id = self._save_draft()

        with patch("app.notifications.service.send_slack_notification", side_effect=RuntimeError("boom")):
            result = service.notify_new_lead(draft_id)

        self.assertFalse(result["slack"])

    def test_skipped_opportunities_do_not_trigger_alerts(self):
        self.settings.slack_notifications_enabled = True
        self.settings.slack_webhook_url = "https://hooks.slack.test/services/1"
        self.settings.email_notifications_enabled = True
        draft_id = self._save_draft(
            response_type="skip",
            should_reply=False,
            comment_text="",
            strategy_reason="Reply would feel promotional.",
        )

        with patch("app.notifications.service.send_slack_notification") as slack_send, patch(
            "app.notifications.service.send_email_notification"
        ) as email_send:
            service.notify_new_lead(draft_id)

        slack_send.assert_not_called()
        email_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
