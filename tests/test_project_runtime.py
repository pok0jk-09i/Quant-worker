import unittest
from unittest import mock
from pathlib import Path

from project_runtime import (
    RuntimeJob,
    RUN_MODE_FULL,
    RUN_MODE_RESEARCH,
    heartbeat_runtime_state,
    build_initial_state,
    build_job_plan,
    build_submission_governance,
    build_submission_summary,
    note_job_progress,
    run_job,
    update_after_job,
    update_runtime_state,
)


class ProjectRuntimeTests(unittest.TestCase):
    def test_build_initial_state_reports_waiting_credentials_when_missing(self):
        state = build_initial_state(credentials_ready=False)

        self.assertEqual(state["status"], "WAITING_CREDENTIALS")
        self.assertEqual(state["project_health"], "DEGRADED")
        self.assertIn("heartbeat_at", state)
        self.assertIn("last_leaf_job", state)

    def test_build_initial_state_reports_booting_when_credentials_ready(self):
        state = build_initial_state(credentials_ready=True)

        self.assertEqual(state["status"], "BOOTING")
        self.assertEqual(state["project_health"], "HEALTHY")
        self.assertFalse(state["submit_enabled"])

    def test_build_job_plan_includes_optional_submit_job(self):
        default_plan = build_job_plan(submit_enabled=False)
        submit_plan = build_job_plan(submit_enabled=True)

        self.assertEqual([job.name for job in default_plan], ["evolve_skill_preview"])
        self.assertEqual(
            [job.name for job in submit_plan],
            ["evolve_skill_preview", "candidate_generate", "candidate_submit"],
        )

    def test_build_initial_state_uses_canonical_full_chain_run_mode(self):
        state = build_initial_state(credentials_ready=True, run_mode=RUN_MODE_FULL)

        self.assertEqual(state["mode"], RUN_MODE_FULL)
        self.assertTrue(state["submit_enabled"])

    def test_build_job_plan_uses_canonical_run_mode(self):
        research_plan = build_job_plan(run_mode=RUN_MODE_RESEARCH)
        full_plan = build_job_plan(run_mode=RUN_MODE_FULL)

        self.assertEqual([job.name for job in research_plan], ["evolve_skill_preview"])
        self.assertEqual(
            [job.name for job in full_plan],
            ["evolve_skill_preview", "candidate_generate", "candidate_submit"],
        )

    def test_update_runtime_state_persists_json(self):
        tmp_path = Path.cwd() / "__tmp_project_runtime_state.json"
        try:
            state = build_initial_state(credentials_ready=False)
            update_runtime_state(tmp_path, state)
            self.assertTrue(tmp_path.exists())
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_note_job_progress_marks_long_running_job_as_running_and_refreshes_heartbeat(self):
        state = build_initial_state(credentials_ready=True)
        state["heartbeat_at"] = "old-heartbeat"
        state["updated_at"] = "old-updated"
        job = RuntimeJob(name="evolve_skill_preview", script=Path("scripts/evolve_skill.py"))

        with mock.patch("project_runtime.now_utc") as mocked_now:
            mocked_now.return_value.isoformat.return_value = "2026-06-28T18:00:00+08:00"
            updated = note_job_progress(state, job, "stage: fetch_pnl 10/200")

        self.assertEqual(updated["status"], "RUNNING")
        self.assertEqual(updated["last_leaf_job"], "evolve_skill_preview")
        self.assertEqual(updated["last_progress"], "stage: fetch_pnl 10/200")
        self.assertEqual(updated["heartbeat_at"], "2026-06-28T18:00:00+08:00")
        self.assertEqual(updated["updated_at"], "2026-06-28T18:00:00+08:00")

    def test_project_runtime_state_uses_ascii_health_values_only(self):
        healthy = build_initial_state(credentials_ready=True)
        waiting = build_initial_state(credentials_ready=False)

        self.assertEqual(healthy["project_health"], "HEALTHY")
        self.assertEqual(waiting["project_health"], "DEGRADED")
        self.assertTrue(healthy["project_health"].isascii())
        self.assertTrue(waiting["project_health"].isascii())

    def test_build_submission_summary_counts_submit_outcomes_from_batch_results(self):
        summary = build_submission_summary(
            [
                {"submission": {"submitted": True, "status": "ACTIVE"}},
                {"submission": {"submitted": True, "status": "PENDING"}},
                {"submission": {"submitted": False, "reason": "metrics_threshold"}},
                {"error": "network failed"},
            ]
        )

        self.assertEqual(
            summary,
            {
                "submitted_active": 1,
                "reused_active": 0,
                "submitted_pending": 1,
                "skipped": 1,
                "skipped_by_threshold": 1,
                "request_errors": 1,
                "platform_rejects": 0,
                "simulation_errors": 0,
                "total": 4,
            },
        )

    def test_build_submission_summary_counts_platform_rejects_and_simulation_errors(self):
        summary = build_submission_summary(
            [
                {"submission": {"submitted": False, "status_code": 400}},
                {"sim": {"status": "ERROR"}},
                {"submission": {"submitted": False, "reason": "metrics_threshold"}},
            ]
        )

        self.assertEqual(summary["platform_rejects"], 1)
        self.assertEqual(summary["simulation_errors"], 1)
        self.assertEqual(summary["skipped_by_threshold"], 1)

    def test_build_submission_summary_tracks_already_submitted_active_as_reused_not_new_submit(self):
        summary = build_submission_summary(
            [
                {
                    "submission": {
                        "submitted": False,
                        "reason": "already_submitted",
                        "status": "ACTIVE",
                    }
                }
            ]
        )

        self.assertEqual(summary["submitted_active"], 0)
        self.assertEqual(summary["reused_active"], 1)
        self.assertEqual(summary["skipped"], 1)

    def test_build_submission_governance_marks_new_active_results_as_healthy(self):
        governance = build_submission_governance(
            {
                "submitted_active": 1,
                "reused_active": 0,
                "submitted_pending": 0,
                "skipped": 1,
                "request_errors": 0,
                "total": 2,
            }
        )

        self.assertEqual(governance["submit_status"], "healthy")
        self.assertEqual(governance["submit_failure_kind"], "none")

    def test_build_submission_governance_marks_all_skipped_results_as_blocked(self):
        governance = build_submission_governance(
            {
                "submitted_active": 0,
                "reused_active": 0,
                "submitted_pending": 0,
                "skipped": 4,
                "skipped_by_threshold": 4,
                "request_errors": 0,
                "platform_rejects": 0,
                "simulation_errors": 0,
                "total": 4,
            }
        )

        self.assertEqual(governance["submit_status"], "blocked")
        self.assertEqual(governance["submit_failure_kind"], "all_skipped_by_threshold")

    def test_build_submission_governance_marks_pending_only_results_as_degraded(self):
        governance = build_submission_governance(
            {
                "submitted_active": 0,
                "reused_active": 0,
                "submitted_pending": 3,
                "skipped": 0,
                "request_errors": 0,
                "platform_rejects": 0,
                "simulation_errors": 0,
                "total": 3,
            }
        )

        self.assertEqual(governance["submit_status"], "degraded")
        self.assertEqual(governance["submit_failure_kind"], "all_pending_timeout")

    def test_build_submission_governance_marks_platform_rejects_as_degraded(self):
        governance = build_submission_governance(
            {
                "submitted_active": 0,
                "reused_active": 0,
                "submitted_pending": 0,
                "skipped": 0,
                "skipped_by_threshold": 0,
                "request_errors": 0,
                "platform_rejects": 2,
                "simulation_errors": 0,
                "total": 2,
            }
        )

        self.assertEqual(governance["submit_status"], "degraded")
        self.assertEqual(governance["submit_failure_kind"], "platform_reject")

    def test_build_submission_governance_marks_partial_success_as_mixed_partial_success(self):
        governance = build_submission_governance(
            {
                "submitted_active": 1,
                "reused_active": 0,
                "submitted_pending": 1,
                "skipped": 0,
                "skipped_by_threshold": 0,
                "request_errors": 1,
                "platform_rejects": 0,
                "simulation_errors": 0,
                "total": 3,
            }
        )

        self.assertEqual(governance["submit_status"], "degraded")
        self.assertEqual(governance["submit_failure_kind"], "mixed_partial_success")

    def test_update_after_submit_job_persists_structured_submission_summary(self):
        state = build_initial_state(credentials_ready=True, run_mode=RUN_MODE_FULL)
        state["submission_summary"] = {}
        job = RuntimeJob(name="submit_batch", script=Path("scripts/submit_batch.py"))
        result = mock.Mock(returncode=0, stdout="", stderr="")

        fake_results_path = Path("E:/Quant worker-CLEAN/wq-alpha-research/batch_submit_results.json")
        fake_payload = [
            {"submission": {"submitted": True, "status": "ACTIVE"}},
            {"submission": {"submitted": False, "reason": "metrics_threshold"}},
        ]

        with mock.patch("project_runtime.now_utc") as mocked_now, mock.patch(
            "project_runtime.SUBMIT_RESULTS_PATH",
            fake_results_path,
        ), mock.patch("project_runtime.load_submit_results", return_value=fake_payload):
            mocked_now.return_value.isoformat.return_value = "2026-06-28T22:00:00+08:00"
            updated = update_after_job(state, job, result)

        self.assertEqual(updated["submission_summary"]["submitted_active"], 1)
        self.assertEqual(updated["submission_summary"]["reused_active"], 0)
        self.assertEqual(updated["submission_summary"]["skipped"], 1)
        self.assertEqual(updated["submission_summary"]["total"], 2)
        self.assertEqual(updated["submit_status"], "healthy")
        self.assertEqual(updated["submit_failure_kind"], "none")

    def test_build_submission_governance_marks_already_submitted_as_blocking_reject(self):
        governance = build_submission_governance(
            {
                "submitted_active": 0,
                "reused_active": 0,
                "submitted_pending": 0,
                "skipped": 0,
                "skipped_by_threshold": 0,
                "request_errors": 0,
                "platform_rejects": 1,
                "simulation_errors": 0,
                "total": 1,
            }
        )

        self.assertEqual(governance["submit_status"], "degraded")
        self.assertEqual(governance["submit_failure_kind"], "platform_reject")

    def test_build_submission_governance_marks_reused_active_results_as_recycled_not_healthy(self):
        governance = build_submission_governance(
            {
                "submitted_active": 0,
                "reused_active": 1,
                "submitted_pending": 0,
                "skipped": 1,
                "skipped_by_threshold": 0,
                "request_errors": 0,
                "platform_rejects": 0,
                "simulation_errors": 0,
                "total": 1,
            }
        )

        self.assertEqual(governance["submit_status"], "blocked")
        self.assertEqual(governance["submit_failure_kind"], "reused_existing_active")

    def test_heartbeat_runtime_state_refreshes_running_job_even_without_new_output(self):
        state = build_initial_state(credentials_ready=True)
        state["status"] = "RUNNING"
        state["last_leaf_job"] = "evolve_skill_preview"
        state["last_progress"] = "stage: fetch_pnl 3343/10000"
        state["heartbeat_at"] = "old-heartbeat"
        state["updated_at"] = "old-updated"

        with mock.patch("project_runtime.now_utc") as mocked_now:
            mocked_now.return_value.isoformat.return_value = "2026-06-28T18:05:00+08:00"
            updated = heartbeat_runtime_state(state)

        self.assertEqual(updated["status"], "RUNNING")
        self.assertEqual(updated["last_leaf_job"], "evolve_skill_preview")
        self.assertEqual(updated["last_progress"], "stage: fetch_pnl 3343/10000")
        self.assertEqual(updated["heartbeat_at"], "2026-06-28T18:05:00+08:00")
        self.assertEqual(updated["updated_at"], "2026-06-28T18:05:00+08:00")

    def test_run_job_streams_output_lines_to_progress_callback(self):
        callback = mock.Mock()
        process = mock.Mock()
        process.wait.return_value = 0
        process.stdout = ["stage: fetch_alphas\n", "stage: fetch_pnl 1/2\n"]
        process.stderr = ["warn: slow page\n"]

        class ImmediateThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                if self._target:
                    self._target(*self._args, **self._kwargs)

            def join(self):
                return None

        with mock.patch("project_runtime.subprocess.Popen", return_value=process), mock.patch(
            "project_runtime.threading.Thread",
            ImmediateThread,
        ):
            result = run_job(
                RuntimeJob(name="evolve_skill_preview", script=Path("scripts/evolve_skill.py")),
                progress_callback=callback,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "stage: fetch_alphas\nstage: fetch_pnl 1/2\n")
        self.assertEqual(result.stderr, "warn: slow page\n")
        self.assertEqual(
            callback.call_args_list,
            [
                mock.call("stdout", "stage: fetch_alphas"),
                mock.call("stdout", "stage: fetch_pnl 1/2"),
                mock.call("stderr", "warn: slow page"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
