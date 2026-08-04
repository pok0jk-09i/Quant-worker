import unittest
from datetime import datetime, timedelta, timezone

from quant_worker_monitor_panel.guardian import browser_health_label, should_reopen_browser


class GuardianTests(unittest.TestCase):
    def test_should_not_reopen_before_first_page_heartbeat(self):
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        last_ping = None
        last_open = now - timedelta(seconds=120)

        self.assertFalse(
            should_reopen_browser(
                last_ping=last_ping,
                last_open=last_open,
                now=now,
                stale_after_seconds=15,
                reopen_cooldown_seconds=10,
            )
        )

    def test_should_reopen_browser_after_stale_ping(self):
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        last_ping = now - timedelta(seconds=31)
        last_open = now - timedelta(seconds=40)

        self.assertTrue(
            should_reopen_browser(
                last_ping=last_ping,
                last_open=last_open,
                now=now,
                stale_after_seconds=15,
                reopen_cooldown_seconds=10,
            )
        )

    def test_should_not_reopen_browser_when_ping_recent(self):
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        last_ping = now - timedelta(seconds=5)
        last_open = now - timedelta(seconds=40)

        self.assertFalse(
            should_reopen_browser(
                last_ping=last_ping,
                last_open=last_open,
                now=now,
                stale_after_seconds=15,
                reopen_cooldown_seconds=10,
            )
        )

    def test_should_reopen_browser_when_last_open_is_recent_but_ping_is_stale(self):
        now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)
        last_ping = now - timedelta(seconds=31)
        last_open = now - timedelta(seconds=3)

        self.assertFalse(
            should_reopen_browser(
                last_ping=last_ping,
                last_open=last_open,
                now=now,
                stale_after_seconds=15,
                reopen_cooldown_seconds=10,
            )
        )

    def test_browser_health_label_is_chinese(self):
        self.assertEqual(browser_health_label(True), "正常")
        self.assertEqual(browser_health_label(False), "异常")


if __name__ == "__main__":
    unittest.main()
