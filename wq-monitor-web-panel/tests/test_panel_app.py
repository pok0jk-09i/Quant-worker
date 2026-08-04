import socket
import unittest
from unittest import mock
import tempfile
from pathlib import Path

import panel_app
from quant_worker_monitor_panel import health
from datetime import datetime, timedelta, timezone


class PanelAppTests(unittest.TestCase):
    def setUp(self):
        health.reset_health_tracker()

    def test_main_binds_http_server_before_opening_browser(self):
        order: list[str] = []
        fake_guard = mock.Mock()
        fake_server = mock.Mock()
        fake_server.serve_forever.side_effect = lambda: order.append("serve_forever")

        def build_server(*_args, **_kwargs):
            order.append("server_created")
            return fake_server

        def open_browser(_url: str) -> bool:
            order.append("browser_open")
            return True

        with mock.patch.object(panel_app, "ensure_single_instance", return_value=fake_guard), mock.patch.object(
            panel_app,
            "choose_port",
            return_value=8765,
        ), mock.patch.object(
            panel_app,
            "persist_state",
        ), mock.patch.object(
            panel_app.threading,
            "Thread",
        ) as thread_cls, mock.patch.object(
            panel_app,
            "ThreadingHTTPServer",
            side_effect=build_server,
        ), mock.patch.object(
            panel_app.webbrowser,
            "open",
            side_effect=open_browser,
        ):
            thread_cls.return_value.start.return_value = None
            panel_app.main()

        self.assertEqual(order[:2], ["server_created", "browser_open"])

    def test_ensure_single_instance_rejects_live_existing_panel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "panel.lock"
            lock_path.write_text('{"pid": 1234}', encoding="utf-8")

            with mock.patch.object(panel_app, "PANEL_LOCK_PATH", lock_path, create=True), mock.patch(
                "panel_app.list_active_python_pids",
                return_value={1234},
            ):
                with self.assertRaises(RuntimeError):
                    panel_app.ensure_single_instance()

    def test_refresh_seconds_defaults_to_fast_monitoring_interval(self):
        self.assertEqual(panel_app.REFRESH_SECONDS, 30)

    def test_choose_port_keeps_preferred_port_when_available(self):
        with mock.patch("panel_app.can_bind_port", return_value=True):
            port = panel_app.choose_port(8765)

        self.assertEqual(port, 8765)

    def test_choose_port_falls_back_when_preferred_port_is_occupied(self):
        with mock.patch("panel_app.can_bind_port", side_effect=[False, True]):
            port = panel_app.choose_port(8765)

        self.assertNotEqual(port, 8765)
        self.assertGreaterEqual(port, 8766)

    def test_can_bind_port_returns_false_for_in_use_port(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        try:
            self.assertFalse(panel_app.can_bind_port(port))
        finally:
            probe.close()

    def test_compute_browser_health_reports_normal_when_page_ping_is_fresh(self):
        now = datetime(2026, 6, 27, 15, 20, tzinfo=timezone.utc)
        last_ping = now - timedelta(seconds=5)
        last_open = now - timedelta(seconds=20)

        health = panel_app.compute_browser_health(
            last_ping=last_ping,
            last_open=last_open,
            now=now,
        )

        self.assertEqual(health, "正常")

    def test_update_loop_seeds_seen_hit_ids_on_first_success_without_popup(self):
        fake_session = object()
        hits = [
            {
                "id": "legacy1",
                "status": "ACTIVE",
                "dateCreated": "2024-01-02T03:04:05-04:00",
                "regular": {"code": "expr1"},
                "is": {"fitness": 1.9, "sharpe": 1.7, "turnover": 0.1},
            }
        ]

        panel_app.SEEN_HIT_IDS.clear()

        with mock.patch.object(panel_app, "create_session", return_value=fake_session), mock.patch.object(
            panel_app, "fetch_top_hits", return_value=hits
        ), mock.patch.object(
            panel_app, "build_summary_lines", return_value=["summary"]
        ), mock.patch.object(
            panel_app, "update_live_state"
        ), mock.patch.object(
            panel_app, "notify"
        ) as notify, mock.patch.object(
            panel_app, "persist_state"
        ), mock.patch.object(
            panel_app.time, "sleep", side_effect=RuntimeError("stop")
        ):
            with self.assertRaises(RuntimeError):
                panel_app.update_loop()

        self.assertEqual(panel_app.SEEN_HIT_IDS, {"legacy1"})
        notify.assert_not_called()

    def test_update_live_state_marks_overall_health_bad_when_submit_status_is_degraded(self):
        with mock.patch.object(
            panel_app,
            "read_project_runtime_state",
            return_value={
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "submit_status": "degraded",
                "submit_failure_kind": "platform_reject",
                "mode": "research+submit",
                "cycle_count": 4,
                "last_leaf_job": "submit_batch",
                "last_progress": "stage: fetch_pnl | 2853/10000",
                "last_error": "",
            },
        ), mock.patch.object(
            panel_app,
            "read_adapter_state",
            return_value={"adapter_status": "RUNNING", "failure_kind": "none", "last_error": ""},
        ):
            panel_app.update_live_state(hits=[], summary=[], error_text="")

        self.assertEqual(panel_app.LATEST["health"], "异常")

    def test_compute_overall_health_requires_all_critical_signals_healthy(self):
        self.assertEqual(
            panel_app.compute_overall_health(
                project_state={"project_health": "HEALTHY", "submit_status": "ready"},
                adapter_state={"adapter_status": "RUNNING", "failure_kind": "none"},
                error_text="",
            ).status,
            "正常",
        )
        self.assertEqual(
            panel_app.compute_overall_health(
                project_state={"project_health": "HEALTHY", "submit_status": "degraded"},
                adapter_state={"adapter_status": "RUNNING", "failure_kind": "none"},
                error_text="",
            ).status,
            "异常",
        )


if __name__ == "__main__":
    unittest.main()
