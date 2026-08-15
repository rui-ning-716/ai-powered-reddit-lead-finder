import tempfile
import unittest
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from app import reddit_client, scanner
from app.campaign import load_campaign
from app.dashboard import render_dashboard
from app.notifications.service import notify_new_lead
from app.reddit_scan_state import (
    FeedTask,
    get_cooldown_state,
    list_feed_schedule,
    mark_feed_success,
    record_rate_limit,
    record_recovery,
    select_feed_tasks,
    sync_campaign_feeds,
)


EMPTY_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return EMPTY_FEED


def http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://www.reddit.com/search.rss", code, "error", headers, None)


def reddit_settings(database_path: str, **overrides):
    values = {
        "database_path": database_path,
        "campaign_path": "campaigns/campaign.yaml",
        "reddit_user_agent": "reddit-lead-finder-test/0.6",
        "reddit_rss_max_retries": 3,
        "reddit_rss_cache_ttl_minutes": 10,
        "reddit_rss_requests_per_tick_min": 3,
        "reddit_rss_requests_per_tick_max": 8,
        "reddit_rss_request_delay_min_seconds": 8,
        "reddit_rss_request_delay_max_seconds": 15,
        "reddit_high_intent_interval_min_minutes": 30,
        "reddit_high_intent_interval_max_minutes": 60,
        "reddit_standard_interval_min_minutes": 120,
        "reddit_standard_interval_max_minutes": 180,
        "reddit_research_interval_min_minutes": 360,
        "reddit_research_interval_max_minutes": 720,
        "reddit_429_cooldown_steps": [120, 240, 480, 720],
        "reddit_429_strike_window_hours": 24,
        "min_manual_scan_interval_minutes": 15,
        "max_ai_posts_per_scan": 8,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def task(task_id: int, query: str = "recommend CRM", campaign: str = "one") -> FeedTask:
    return FeedTask(
        id=task_id,
        campaign_key=campaign,
        feed_url=f"https://www.reddit.com/search.rss?q={task_id}",
        keyword=query,
        subreddit="all",
        tier="high",
        next_due_at=0,
    )


class RedditRateLimitTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = str(Path(self.temporary_directory.name) / "test.sqlite3")
        self.settings = reddit_settings(self.database_path)
        self.campaign = load_campaign("campaigns/campaign.yaml")
        self.patchers = [
            patch("app.db.get_settings", return_value=self.settings),
            patch("app.reddit_scan_state.get_settings", return_value=self.settings),
            patch("app.reddit_client.get_settings", return_value=self.settings),
            patch("app.scanner.get_settings", return_value=self.settings),
        ]
        for patcher in self.patchers:
            patcher.start()
        reddit_client._FEED_CACHE.clear()
        reddit_client._LAST_RSS_REQUEST_AT = None
        reddit_client.reset_circuit_breaker()
        reddit_client.begin_reddit_scan(self.campaign)
        scanner._LAST_MANUAL_SCAN_AT = None

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def test_first_429_stops_remaining_requests_and_opens_global_cooldown(self):
        tasks = [task(1), task(2), task(3)]
        with patch("urllib.request.urlopen", side_effect=http_error(429)) as urlopen:
            posts = list(
                reddit_client.search_posts(
                    campaign=self.campaign,
                    feed_tasks=tasks,
                    manage_scan=False,
                )
            )

        self.assertEqual(posts, [])
        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(reddit_client.is_circuit_open())
        self.assertEqual(reddit_client.get_fetch_stats()["rate_limited_requests"], 1)
        self.assertGreaterEqual(get_cooldown_state().remaining_seconds(), 119 * 60)

    def test_429_is_not_retried_or_slept(self):
        with patch("urllib.request.urlopen", side_effect=http_error(429)) as urlopen, patch(
            "app.reddit_client.time.sleep"
        ) as sleep:
            reddit_client._read_feed(task(1).feed_url, "test")

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_retry_after_is_persisted_exactly(self):
        with patch("app.reddit_scan_state.time.time", return_value=1000), patch(
            "urllib.request.urlopen", side_effect=http_error(429, retry_after="7")
        ):
            reddit_client._read_feed(task(1).feed_url, "test")

        state = get_cooldown_state()
        self.assertEqual(state.cooldown_until, 1007)
        self.assertEqual(state.retry_after_seconds, 7)

    def test_missing_retry_after_escalates_2_4_8_12_hours(self):
        observed = []
        for now in (1000, 1001, 1002, 1003, 1004):
            state = record_rate_limit(None, now=now)
            observed.append(round((state.cooldown_until - now) / 3600))

        self.assertEqual(observed, [2, 4, 8, 12, 12])
        self.assertEqual(get_cooldown_state().strike_count, 5)

    def test_cooldown_state_survives_process_memory_reset(self):
        record_rate_limit(None, now=1000)
        reddit_client._FEED_CACHE.clear()
        reddit_client._SCAN_ABORTED = False

        state_after_restart = get_cooldown_state()

        self.assertEqual(state_after_restart.strike_count, 1)
        self.assertEqual(state_after_restart.cooldown_until, 1000 + 2 * 60 * 60)

    def test_success_does_not_erase_recent_429_escalation_history(self):
        record_rate_limit(None, now=1000)
        record_recovery(now=1000 + 2 * 60 * 60 + 1)

        second = record_rate_limit(None, now=1000 + 2 * 60 * 60 + 2)

        self.assertEqual(second.strike_count, 2)
        self.assertEqual(round((second.cooldown_until - (1000 + 2 * 60 * 60 + 2)) / 3600), 4)

    def test_legacy_rss_scan_during_cooldown_makes_zero_reddit_requests(self):
        reddit_client.open_circuit()
        with patch("urllib.request.urlopen") as urlopen:
            posts = list(reddit_client.search_posts(
                campaign=self.campaign,
                feed_tasks=[task(1)],
                manage_scan=False,
            ))

        self.assertEqual(posts, [])
        self.assertEqual(reddit_client.get_fetch_stats()["rss_requests"], 0)
        urlopen.assert_not_called()

    def test_feed_schedule_round_robins_campaigns(self):
        feeds = [
            {"feed_url": "https://example.com/1", "keyword": "one", "subreddit": "all", "tier": "high"},
            {"feed_url": "https://example.com/2", "keyword": "two", "subreddit": "all", "tier": "standard"},
        ]
        sync_campaign_feeds("alpha", feeds)
        sync_campaign_feeds("beta", [dict(item, feed_url=item["feed_url"] + "b") for item in feeds])

        selected = select_feed_tasks(["alpha", "beta"], 4, now=1000)

        self.assertEqual([item.campaign_key for item in selected], ["alpha", "beta", "alpha", "beta"])

    def test_scheduler_request_budget_stays_between_three_and_eight(self):
        with patch("app.reddit_client.random.randint", return_value=5) as randint:
            budget = reddit_client.request_budget_for_tick(self.settings)

        self.assertEqual(budget, 5)
        randint.assert_called_once_with(3, 8)

    def test_success_uses_tier_specific_next_due_time(self):
        sync_campaign_feeds(
            "alpha",
            [{"feed_url": "https://example.com/1", "keyword": "one", "subreddit": "all", "tier": "high"}],
        )
        selected = select_feed_tasks(["alpha"], 1, now=1000)
        mark_feed_success(selected[0].id, "high", now=1000, interval_minutes=45)

        row = list_feed_schedule("alpha")[0]
        self.assertEqual(row["last_success_at"], 1000)
        self.assertEqual(row["next_due_at"], 1000 + 45 * 60)

    def test_core_and_research_feeds_receive_different_tiers(self):
        descriptors = reddit_client.build_feed_descriptors(self.campaign)
        tier_by_pair = {
            (item["subreddit"], item["keyword"]): item["tier"] for item in descriptors
        }

        self.assertEqual(tier_by_pair[("all", '"Otter alternative"')], "high")
        self.assertEqual(tier_by_pair[("all", '"meeting notes tool"')], "standard")
        self.assertEqual(tier_by_pair[("SaaS", '"Otter alternative"')], "research")

    def test_requests_are_spaced_by_configured_delay(self):
        with patch("urllib.request.urlopen", return_value=FakeResponse()), patch(
            "app.reddit_client.time.monotonic", side_effect=[100, 100, 102, 110, 110]
        ), patch("app.reddit_client.time.sleep") as sleep:
            reddit_client._read_feed("https://example.com/one", "one", delay_before_fetch=10)
            reddit_client._read_feed("https://example.com/two", "two", delay_before_fetch=10)

        sleep.assert_called_once_with(8)

    def test_temporary_5xx_still_uses_bounded_retry(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=[http_error(500), http_error(502), FakeResponse()],
        ), patch("app.reddit_client.random.uniform", return_value=0), patch(
            "app.reddit_client.time.sleep"
        ) as sleep:
            reddit_client._read_feed("https://example.com/retry", "test")

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60])

    def test_dashboard_and_notifications_remain_available_during_cooldown(self):
        reddit_client.open_circuit()

        html = render_dashboard([], {"posts_seen": 0, "leads_total": 0, "by_status": {}})
        with patch("app.notifications.service.get_draft", return_value=None):
            notification_result = notify_new_lead(999)

        self.assertIn("Reddit Lead Finder", html)
        self.assertEqual(notification_result, {"slack": False, "email": False})

    def test_scan_lock_returns_already_running(self):
        acquired = scanner._SCAN_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            result = scanner.run_scan(manual=True)
        finally:
            scanner._SCAN_LOCK.release()

        self.assertEqual(result["status"], "already_running")


if __name__ == "__main__":
    unittest.main()
