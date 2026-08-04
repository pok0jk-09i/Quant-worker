import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import adapter_host


class AdapterHostStateTests(unittest.TestCase):
    def test_ensure_single_instance_rejects_live_existing_adapter_host(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "adapter.lock"
            lock_path.write_text('{"pid": 4321}', encoding="utf-8")

            with mock.patch.object(adapter_host, "ADAPTER_LOCK_PATH", lock_path, create=True), mock.patch(
                "adapter_host.list_active_python_pids",
                return_value={4321},
            ):
                with self.assertRaises(RuntimeError):
                    adapter_host.ensure_single_instance()

    def test_build_supervised_state_reports_missing_submit_chain_in_research_mode(self):
        state = adapter_host.build_supervised_state(
            {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research",
                "submit_enabled": False,
                "last_leaf_job": "evolve_skill_preview",
                "last_exit_code": 0,
            }
        )

        self.assertEqual(state["coverage_status"], "partial")
        self.assertIn("submit_batch", state["missing_capabilities"])

    def test_build_supervised_state_keeps_partial_coverage_for_running_research_only_runtime(self):
        state = adapter_host.build_supervised_state(
            {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research",
                "submit_enabled": False,
                "last_leaf_job": "evolve_skill_preview",
                "last_progress": "stage: fetch_pnl | 3343/10000",
                "last_exit_code": 0,
            }
        )

        self.assertEqual(state["adapter_status"], "RUNNING")
        self.assertEqual(state["coverage_status"], "partial")
        self.assertEqual(state["active_capabilities"], ["evolve_skill_preview", "candidate_generate"])
        self.assertEqual(state["missing_capabilities"], ["submit_batch", "candidate_submit"])

    def test_build_supervised_state_reports_full_coverage_for_canonical_full_chain_mode(self):
        state = adapter_host.build_supervised_state(
            {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research+submit",
                "submit_enabled": True,
                "last_leaf_job": "submit_batch",
                "last_exit_code": 0,
            }
        )

        self.assertEqual(state["coverage_status"], "full")
        self.assertEqual(
            state["active_capabilities"],
            ["evolve_skill_preview", "candidate_generate", "candidate_submit", "submit_batch"],
        )
        self.assertEqual(state["missing_capabilities"], [])

    def test_build_supervised_state_emits_supervisor_contract_with_chain_verdicts(self):
        state = adapter_host.build_supervised_state(
            {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research+submit",
                "submit_enabled": True,
                "last_leaf_job": "evolve_skill_preview",
                "last_progress": "stage: fetch_pnl | 4803/10000",
                "last_exit_code": 0,
            },
            alpha_db_present=False,
        )

        self.assertEqual(state["authority_map"]["project_runtime_state"], "authority")
        self.assertEqual(state["workflow_verdicts"]["production_chain"]["state"], "ready")
        self.assertEqual(state["workflow_verdicts"]["research_chain"]["state"], "partial")
        self.assertIn("生产链已接入", state["workflow_verdicts"]["production_chain"]["summary"])

    def test_build_supervised_state_marks_submit_chain_as_stale_when_only_historical_submit_results_exist(self):
        state = adapter_host.build_supervised_state(
            {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research+submit",
                "submit_enabled": True,
                "last_leaf_job": "evolve_skill_preview",
                "updated_at": "2026-06-29T05:58:00+00:00",
                "last_exit_code": 0,
            },
            submit_results=[{"submission": {"submitted": False, "reason": "metrics_threshold"}}],
            submit_results_updated_at="2026-06-29T04:36:05+00:00",
        )

        self.assertEqual(state["workflow_verdicts"]["submit_chain"]["state"], "partial")
        self.assertIn("历史", state["workflow_verdicts"]["submit_chain"]["root_cause"])

    def test_main_publishes_complete_supervised_state_on_first_persist_after_bootstrap(self):
        process = mock.Mock()
        process.poll.side_effect = [0]
        process.terminate = mock.Mock()
        bootstrapped_state = {
            "status": "RUNNING",
            "project_health": "HEALTHY",
            "mode": "research+submit",
            "submit_enabled": True,
            "last_leaf_job": "evolve_skill_preview",
            "last_exit_code": 0,
        }

        with mock.patch.object(adapter_host, "ensure_single_instance") as ensure_guard, mock.patch.object(
            adapter_host, "run_project_runtime", return_value=process
        ), mock.patch.object(
            adapter_host, "read_project_state", return_value=bootstrapped_state
        ), mock.patch.object(
            adapter_host, "bootstrap_runtime_state", return_value=bootstrapped_state
        ), mock.patch.object(
            adapter_host, "persist_state"
        ) as persist_state, mock.patch.object(
            adapter_host, "STATE_DIR", Path(tempfile.gettempdir())
        ), mock.patch.object(
            adapter_host, "load_credentials", return_value=("user", "pass")
        ):
            ensure_guard.return_value = mock.Mock(release=mock.Mock())
            rc = adapter_host.main()

        first_payload = persist_state.call_args_list[0].args[0]
        self.assertEqual(first_payload["coverage_status"], "full")
        self.assertEqual(first_payload["project_state"]["mode"], "research+submit")
        self.assertTrue(first_payload["project_state"]["submit_enabled"])
        self.assertEqual(rc, 0)

    def test_main_writes_adapter_state_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            state_path = state_dir / "adapter_state.json"
            project_state_path = state_dir / "project_runtime_state.json"
            lock_path = state_dir / "adapter_host.lock"
            project_state_path.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "project_health": "HEALTHY",
                        "last_leaf_job": "evolve_skill_preview",
                        "last_exit_code": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            process = mock.Mock()
            process.poll.side_effect = [None, None, 0]
            process.terminate = mock.Mock()

            with mock.patch.object(adapter_host, "STATE_DIR", state_dir), mock.patch.object(
                adapter_host, "ADAPTER_STATE_PATH", state_path, create=True
            ), mock.patch.object(
                adapter_host, "PROJECT_STATE_PATH", project_state_path, create=True
            ), mock.patch.object(
                adapter_host, "ADAPTER_LOCK_PATH", lock_path, create=True
            ), mock.patch.object(
                adapter_host, "HEARTBEAT_SECONDS", 0
            ), mock.patch.object(
                adapter_host, "load_credentials", return_value=("user", "pass")
            ), mock.patch.object(
                adapter_host, "list_active_python_pids", return_value=set()
            ), mock.patch.object(
                adapter_host, "run_project_runtime", return_value=process
            ):
                rc = adapter_host.main()

            self.assertTrue(state_path.exists())
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["adapter_status"], "RUNNING")
            self.assertEqual(payload["last_leaf_job"], "evolve_skill_preview")
            self.assertEqual(payload["project_state"]["status"], "RUNNING")
            self.assertIn("coverage_status", payload)
            self.assertEqual(rc, 0)

    def test_main_bootstraps_from_fresh_runtime_state_before_first_supervised_publish(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            state_path = state_dir / "adapter_state.json"
            project_state_path = state_dir / "project_runtime_state.json"
            lock_path = state_dir / "adapter_host.lock"
            project_state_path.write_text(
                json.dumps(
                    {
                        "status": "RUNNING",
                        "project_health": "HEALTHY",
                        "mode": "research",
                        "submit_enabled": False,
                        "last_leaf_job": "evolve_skill_preview",
                        "updated_at": "2026-06-28T14:11:02.413992+00:00",
                        "last_exit_code": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            process = mock.Mock()
            process.poll.side_effect = [None, 0]
            process.terminate = mock.Mock()

            fresh_runtime_state = {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research+submit",
                "submit_enabled": True,
                "last_leaf_job": "evolve_skill_preview",
                "updated_at": "2026-06-28T14:12:20.588372+00:00",
                "last_exit_code": 0,
            }

            read_states = [
                json.loads(project_state_path.read_text(encoding="utf-8")),
                fresh_runtime_state,
                fresh_runtime_state,
            ]

            def fake_read_project_state():
                if read_states:
                    return read_states.pop(0)
                return fresh_runtime_state

            with mock.patch.object(adapter_host, "STATE_DIR", state_dir), mock.patch.object(
                adapter_host, "ADAPTER_STATE_PATH", state_path, create=True
            ), mock.patch.object(
                adapter_host, "PROJECT_STATE_PATH", project_state_path, create=True
            ), mock.patch.object(
                adapter_host, "ADAPTER_LOCK_PATH", lock_path, create=True
            ), mock.patch.object(
                adapter_host, "HEARTBEAT_SECONDS", 0
            ), mock.patch.object(
                adapter_host, "load_credentials", return_value=("user", "pass")
            ), mock.patch.object(
                adapter_host, "list_active_python_pids", return_value=set()
            ), mock.patch.object(
                adapter_host, "run_project_runtime", return_value=process
            ), mock.patch.object(
                adapter_host, "read_project_state", side_effect=fake_read_project_state
            ):
                rc = adapter_host.main()

            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["coverage_status"], "full")
            self.assertEqual(payload["project_state"]["mode"], "research+submit")
            self.assertTrue(payload["project_state"]["submit_enabled"])
            self.assertEqual(rc, 0)

    def test_main_initial_booting_publish_uses_fresh_runtime_mode_not_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir)
            state_path = state_dir / "adapter_state.json"
            project_state_path = state_dir / "project_runtime_state.json"
            lock_path = state_dir / "adapter_host.lock"
            stale_runtime_state = {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research",
                "submit_enabled": False,
                "last_leaf_job": "evolve_skill_preview",
                "updated_at": "2026-06-28T14:11:02.413992+00:00",
                "last_exit_code": 0,
            }
            project_state_path.write_text(json.dumps(stale_runtime_state, ensure_ascii=False), encoding="utf-8")

            process = mock.Mock()
            process.poll.side_effect = [0]
            process.terminate = mock.Mock()

            fresh_runtime_state = {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research+submit",
                "submit_enabled": True,
                "last_leaf_job": "evolve_skill_preview",
                "updated_at": "2026-06-28T14:12:20.588372+00:00",
                "last_exit_code": 0,
            }

            persisted_states: list[dict[str, object]] = []

            def fake_persist_state(state: dict[str, object]) -> None:
                persisted_states.append(json.loads(json.dumps(state)))

            with mock.patch.object(adapter_host, "STATE_DIR", state_dir), mock.patch.object(
                adapter_host, "ADAPTER_STATE_PATH", state_path, create=True
            ), mock.patch.object(
                adapter_host, "PROJECT_STATE_PATH", project_state_path, create=True
            ), mock.patch.object(
                adapter_host, "ADAPTER_LOCK_PATH", lock_path, create=True
            ), mock.patch.object(
                adapter_host, "HEARTBEAT_SECONDS", 0
            ), mock.patch.object(
                adapter_host, "load_credentials", return_value=("user", "pass")
            ), mock.patch.object(
                adapter_host, "list_active_python_pids", return_value=set()
            ), mock.patch.object(
                adapter_host, "run_project_runtime", return_value=process
            ), mock.patch.object(
                adapter_host,
                "read_project_state",
                side_effect=[stale_runtime_state, fresh_runtime_state, fresh_runtime_state],
            ), mock.patch.object(
                adapter_host, "persist_state", side_effect=fake_persist_state
            ):
                adapter_host.main()

            self.assertGreaterEqual(len(persisted_states), 2)
            self.assertEqual(persisted_states[0]["adapter_status"], "RUNNING")
            self.assertEqual(persisted_states[0]["coverage_status"], "full")
            self.assertEqual(persisted_states[0]["project_state"]["mode"], "research+submit")
            self.assertTrue(persisted_states[0]["project_state"]["submit_enabled"])


if __name__ == "__main__":
    unittest.main()
