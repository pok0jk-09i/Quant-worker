import unittest
from unittest import mock
import json

import panel_app
from quant_worker_monitor_panel.core import build_adapter_summary_lines


class AdapterStatePanelTests(unittest.TestCase):
    def test_adapter_summary_reports_contract_mismatch(self):
        lines = build_adapter_summary_lines(
            {
                "adapter_status": "DEGRADED",
                "failure_kind": "contract_mismatch",
                "last_error": "Invalid offset",
                "authority_map": {
                    "project_runtime_state": "authority",
                    "batch_submit_results": "authority",
                    "project_runtime_log": "authority",
                    "adapter_state": "derived",
                    "panel_state": "display_only",
                },
                "workflow_verdicts": {
                    "research_chain": {"state": "partial", "summary": "研究快照工作流运行中", "root_cause": "preview 模式未写入 alpha_db"},
                    "submit_chain": {"state": "complete", "summary": "固定模板提交治理链可用", "root_cause": ""},
                    "production_chain": {"state": "broken", "summary": "新因子生产链未接入", "root_cause": "runtime 仅编排研究快照脚本和固定模板 submit 脚本"},
                    "truth_closure_chain": {"state": "partial", "summary": "研究记忆真相未闭合", "root_cause": "alpha_db durable writeback 缺失"},
                },
                "next_attention": "runtime 仅编排研究快照脚本和固定模板 submit 脚本",
            }
        )

        self.assertTrue(any("contract_mismatch" in line for line in lines))
        self.assertTrue(any("新因子生产链未接入" in line for line in lines))
        self.assertTrue(any("研究快照工作流运行中" in line for line in lines))
        self.assertTrue(any("下一注意点" in line for line in lines))

    def test_panel_updates_adapter_summary_from_external_state(self):
        with mock.patch.object(
            panel_app,
            "read_project_runtime_state",
            return_value={"status": "RUNNING", "project_health": "HEALTHY", "last_leaf_job": "submit_batch"},
        ), mock.patch.object(
            panel_app,
            "read_adapter_state",
            return_value={
                "adapter_status": "DEGRADED",
                "failure_kind": "contract_mismatch",
                "last_error": "Invalid offset",
                "last_leaf_job": "evolve_skill_preview",
            },
        ):
            panel_app.update_live_state(hits=[], summary=[], error_text="")

        self.assertEqual(panel_app.LATEST["adapter_state"]["adapter_status"], "DEGRADED")
        self.assertTrue(any("contract_mismatch" in line for line in panel_app.LATEST["adapter_summary"]))

    def test_panel_exposes_project_progress_summary_for_highlight(self):
        with mock.patch.object(
            panel_app,
            "read_project_runtime_state",
            return_value={
                "status": "BOOTING",
                "project_health": "HEALTHY",
                "last_leaf_job": "evolve_skill_preview",
                "last_progress": "stage: fetch_pnl | 1097/10000",
            },
        ), mock.patch.object(
            panel_app,
            "read_adapter_state",
            return_value={"adapter_status": "RUNNING", "failure_kind": "none", "last_error": "", "last_leaf_job": ""},
        ):
            panel_app.update_live_state(hits=[], summary=[], error_text="")

        self.assertEqual(panel_app.LATEST["project_progress"], "正在抓取 PnL: 1097/10000 (10.97%)")

    def test_state_handler_refreshes_live_project_progress_before_responding(self):
        panel_app.LATEST.update({"project_progress": "", "project_summary": []})

        with mock.patch.object(
            panel_app,
            "read_project_runtime_state",
            return_value={
                "status": "BOOTING",
                "project_health": "HEALTHY",
                "last_leaf_job": "evolve_skill_preview",
                "last_progress": "stage: fetch_pnl | 2905/10000",
            },
        ), mock.patch.object(
            panel_app,
            "read_adapter_state",
            return_value={"adapter_status": "RUNNING", "failure_kind": "none", "last_error": "", "last_leaf_job": ""},
        ), mock.patch.object(
            panel_app.Handler,
            "send_response",
        ), mock.patch.object(
            panel_app.Handler,
            "send_header",
        ), mock.patch.object(
            panel_app.Handler,
            "end_headers",
        ):
            handler = panel_app.Handler.__new__(panel_app.Handler)
            handler.path = "/state"
            handler.wfile = mock.Mock()
            panel_app.Handler.do_GET(handler)

        payload = json.loads(handler.wfile.write.call_args.args[0].decode("utf-8"))
        self.assertEqual(payload["project_progress"], "正在抓取 PnL: 2905/10000 (29.05%)")


if __name__ == "__main__":
    unittest.main()
