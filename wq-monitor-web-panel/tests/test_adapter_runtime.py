import unittest

from adapter_host import build_runtime_state, build_supervised_state


class AdapterRuntimeTests(unittest.TestCase):
    def test_runtime_state_marks_contract_mismatch_as_degraded(self):
        state = build_runtime_state("contract_mismatch", "Invalid offset", 1, "evolve_skill_preview")

        self.assertEqual(state["adapter_status"], "DEGRADED")
        self.assertEqual(state["failure_kind"], "contract_mismatch")
        self.assertEqual(state["last_leaf_job"], "evolve_skill_preview")

    def test_supervised_state_inherits_project_failure_as_adapter_degraded(self):
        state = build_supervised_state(
            {
                "status": "DEGRADED",
                "last_exit_code": 1,
                "last_leaf_job": "evolve_skill_preview",
                "last_error": "Failed to fetch alphas: 400 Invalid offset",
            }
        )

        self.assertEqual(state["adapter_status"], "DEGRADED")
        self.assertEqual(state["failure_kind"], "contract_mismatch")
        self.assertEqual(state["project_state"]["status"], "DEGRADED")


if __name__ == "__main__":
    unittest.main()
