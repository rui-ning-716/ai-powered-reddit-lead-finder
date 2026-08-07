import unittest
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch

from app import reddit_client, scanner
from app.dashboard import render_dashboard
from app.notifications.service import notify_new_lead


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


def reddit_settings(**overrides):
    values = {
        "reddit_user_agent": "threadscout-test/0.1",
        "reddit_rss_max_retries": 3,
        "reddit_rss_cache_ttl_minutes": 10,
        "reddit_429_circuit_breaker_threshold": 3,
        "reddit_429_cooldown_minutes": 120,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RedditRateLimitTest(unittest.TestCase):
    def setUp(self):
        reddit_client._FEED_CACHE.clear()
        reddit_client.reset_circuit_breaker()
        reddit_client.reset_fetch_stats()

    def test_429_handling_returns_empty_feed_without_crashing(self):
        with patch("app.reddit_client.get_settings", return_value=reddit_settings(reddit_rss_max_retries=0)), patch(
            "urllib.request.urlopen", side_effect=http_error(429)
        ):
            posts = reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        self.assertEqual(posts, [])
        self.assertEqual(reddit_client.get_fetch_stats()["rate_limited_requests"], 1)
        self.assertEqual(reddit_client.get_fetch_stats()["circuit_state"], "closed")

    def test_one_429_does_not_immediately_open_circuit(self):
        with patch("app.reddit_client.get_settings", return_value=reddit_settings(reddit_rss_max_retries=0)), patch(
            "urllib.request.urlopen", side_effect=http_error(429)
        ):
            reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        self.assertEqual(reddit_client.get_fetch_stats()["rate_limited_requests"], 1)
        self.assertEqual(reddit_client.get_fetch_stats()["circuit_state"], "closed")

    def test_reaching_threshold_opens_circuit(self):
        settings = reddit_settings(reddit_rss_max_retries=0, reddit_429_circuit_breaker_threshold=3)
        with patch("app.reddit_client.get_settings", return_value=settings), patch(
            "urllib.request.urlopen", side_effect=[http_error(429), http_error(429), http_error(429)]
        ):
            for index in range(3):
                reddit_client._read_feed(f"https://www.reddit.com/search.rss?q=test{index}", "test")

        stats = reddit_client.get_fetch_stats()
        self.assertEqual(stats["rate_limited_requests"], 3)
        self.assertEqual(stats["circuit_state"], "open")
        self.assertTrue(stats["circuit_breaker_triggered"])

    def test_remaining_rss_requests_are_skipped_after_circuit_opens(self):
        settings = reddit_settings(reddit_rss_max_retries=0, reddit_429_circuit_breaker_threshold=3)
        with patch("app.reddit_client.get_settings", return_value=settings), patch(
            "urllib.request.urlopen", side_effect=http_error(429)
        ) as urlopen:
            list(reddit_client.search_posts())

        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(reddit_client.get_fetch_stats()["circuit_state"], "open")

    def test_scheduled_scan_during_cooldown_makes_zero_reddit_requests(self):
        settings = reddit_settings(
            reddit_rss_max_retries=0,
            reddit_429_circuit_breaker_threshold=3,
            reddit_429_cooldown_minutes=120,
            max_ai_posts_per_scan=8,
        )
        with patch("app.reddit_client.get_settings", return_value=settings):
            reddit_client.open_circuit()

        with patch("app.scanner.get_settings", return_value=settings), patch(
            "app.reddit_client.get_settings", return_value=settings
        ), patch("urllib.request.urlopen") as urlopen:
            result = scanner._run_scan_unlocked()

        self.assertEqual(result["status"], "reddit_rate_limit_cooldown")
        self.assertEqual(result["rss_requests"], 0)
        urlopen.assert_not_called()

    def test_after_cooldown_expires_enters_half_open(self):
        reddit_client._CIRCUIT_STATE = "open"
        reddit_client._CIRCUIT_OPEN_UNTIL = 0

        with patch("app.reddit_client.time.monotonic", return_value=10):
            reddit_client.begin_reddit_scan()

        self.assertEqual(reddit_client.get_fetch_stats()["circuit_state"], "half_open")

    def test_successful_half_open_test_closes_circuit(self):
        reddit_client._CIRCUIT_STATE = "open"
        reddit_client._CIRCUIT_OPEN_UNTIL = 0

        with patch("app.reddit_client.get_settings", return_value=reddit_settings()), patch(
            "urllib.request.urlopen", return_value=FakeResponse()
        ):
            reddit_client.begin_reddit_scan()
            reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        self.assertEqual(reddit_client.get_fetch_stats()["circuit_state"], "closed")

    def test_429_during_half_open_reopens_circuit(self):
        reddit_client._CIRCUIT_STATE = "open"
        reddit_client._CIRCUIT_OPEN_UNTIL = 0
        settings = reddit_settings(reddit_rss_max_retries=0)

        with patch("app.reddit_client.get_settings", return_value=settings), patch(
            "urllib.request.urlopen", side_effect=http_error(429)
        ):
            reddit_client.begin_reddit_scan()
            reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        self.assertEqual(reddit_client.get_fetch_stats()["circuit_state"], "open")

    def test_retry_after_header_is_respected(self):
        with patch("app.reddit_client.get_settings", return_value=reddit_settings(reddit_rss_max_retries=1)), patch(
            "urllib.request.urlopen", side_effect=[http_error(429, retry_after="7"), FakeResponse()]
        ), patch("time.sleep") as sleep:
            posts = reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        self.assertEqual(posts, [])
        sleep.assert_called_once_with(7.0)

    def test_exponential_backoff_for_temporary_5xx(self):
        with patch("app.reddit_client.get_settings", return_value=reddit_settings(reddit_rss_max_retries=2)), patch(
            "urllib.request.urlopen",
            side_effect=[http_error(500), http_error(502), FakeResponse()],
        ), patch("app.reddit_client.random.uniform", return_value=0), patch("time.sleep") as sleep:
            reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 60])

    def test_scan_lock_returns_already_running(self):
        acquired = scanner._SCAN_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            result = scanner.run_scan(manual=True)
        finally:
            scanner._SCAN_LOCK.release()

        self.assertEqual(result["status"], "already_running")

    def test_manual_scan_cooldown(self):
        scanner._LAST_MANUAL_SCAN_AT = None
        settings = SimpleNamespace(min_manual_scan_interval_minutes=15)

        with patch("app.scanner.get_settings", return_value=settings), patch(
            "app.scanner._run_scan_unlocked", return_value={"status": "completed"}
        ), patch("app.scanner.time.monotonic", side_effect=[1000, 1010]):
            first = scanner.run_scan(manual=True)
            second = scanner.run_scan(manual=True)

        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "cooldown")
        self.assertGreater(second["retry_after_seconds"], 0)
        scanner._LAST_MANUAL_SCAN_AT = None

    def test_dashboard_and_notifications_survive_rate_limited_fetch(self):
        with patch("app.reddit_client.get_settings", return_value=reddit_settings(reddit_rss_max_retries=0)), patch(
            "urllib.request.urlopen", side_effect=http_error(429)
        ):
            posts = reddit_client._read_feed("https://www.reddit.com/search.rss?q=test", "test")

        html = render_dashboard([], {"posts_seen": 0, "leads_total": 0, "by_status": {}})
        with patch("app.notifications.service.get_draft", return_value=None):
            notification_result = notify_new_lead(999)

        self.assertEqual(posts, [])
        self.assertIn("Reddit Lead Finder", html)
        self.assertEqual(notification_result, {"slack": False, "email": False})

    def test_circuit_breaker_events_do_not_send_notifications(self):
        settings = reddit_settings(
            reddit_rss_max_retries=0,
            reddit_429_circuit_breaker_threshold=3,
            reddit_429_cooldown_minutes=120,
            max_ai_posts_per_scan=8,
        )
        with patch("app.reddit_client.get_settings", return_value=settings):
            reddit_client.open_circuit()

        with patch("app.scanner.get_settings", return_value=settings), patch(
            "app.reddit_client.get_settings", return_value=settings
        ), patch("app.scanner.notify_new_lead") as notify:
            scanner._run_scan_unlocked()

        notify.assert_not_called()

    def test_keyword_consolidation_reduces_rss_requests(self):
        report = reddit_client.keyword_consolidation_report()

        self.assertEqual(report["before_count"], 4)
        self.assertEqual(report["after_count"], 4)

    def test_distinct_intent_categories_remain_after_consolidation(self):
        keywords = reddit_client.consolidated_keywords()

        self.assertIn('"meeting notes tool"', keywords)
        self.assertIn('"AI meeting assistant"', keywords)


if __name__ == "__main__":
    unittest.main()
