import os
import unittest
from unittest import mock

import adapter_host
from adapter_host import classify_failure


class AdapterHostContractTests(unittest.TestCase):
    def test_classify_failure_marks_invalid_offset_as_contract_mismatch(self):
        kind = classify_failure(
            'RuntimeError: Failed to fetch alphas: 400 ["Invalid offset. Please use filters to narrow down the result."]'
        )
        self.assertEqual(kind, "contract_mismatch")

    def test_run_project_runtime_passes_canonical_full_chain_contract_to_runtime(self):
        with mock.patch.object(adapter_host, "load_credentials", return_value=("user", "pass")), mock.patch(
            "adapter_host.subprocess.Popen"
        ) as popen:
            adapter_host.run_project_runtime(run_mode="research+submit")

        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["QUANT WORKER_RUN_MODE"], "research+submit")
        self.assertEqual(env["QUANT WORKER_RUNTIME_ENABLE_SUBMIT"], "1")

    def test_run_project_runtime_passes_research_only_contract_to_runtime(self):
        with mock.patch.object(adapter_host, "load_credentials", return_value=("user", "pass")), mock.patch(
            "adapter_host.subprocess.Popen"
        ) as popen:
            adapter_host.run_project_runtime(run_mode="research")

        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["QUANT WORKER_RUN_MODE"], "research")
        self.assertEqual(env["QUANT WORKER_RUNTIME_ENABLE_SUBMIT"], "0")


if __name__ == "__main__":
    unittest.main()
