import unittest

from quant_worker_monitor_panel.core import (
    build_adapter_summary_lines,
    build_offline_summary_lines,
    build_project_summary_lines,
    build_summary_lines,
    extract_metrics,
    format_alpha_card,
    select_qualifying_alphas,
)


class CoreTests(unittest.TestCase):
    def test_select_qualifying_alphas_filters_and_sorts(self):
        alphas = [
            {
                "id": "a1",
                "status": "ACTIVE",
                "settings": {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 0, "neutralization": "SUBINDUSTRY"},
                "regular": {"code": "expr1"},
                "is": {"fitness": 1.20, "sharpe": 1.80, "turnover": 0.10},
            },
            {
                "id": "a2",
                "status": "ACTIVE",
                "settings": {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 0, "neutralization": "SUBINDUSTRY"},
                "regular": {"code": "expr2"},
                "is": {"fitness": 1.90, "sharpe": 1.60, "turnover": 0.10},
            },
            {
                "id": "a3",
                "status": "UNSUBMITTED",
                "settings": {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 0, "neutralization": "SUBINDUSTRY"},
                "regular": {"code": "expr3"},
                "is": {"fitness": 1.75, "sharpe": 1.50, "turnover": 0.10},
            },
        ]

        hits = select_qualifying_alphas(alphas, threshold=1.7, status_filter="ANY", max_items=10)

        self.assertEqual([a["id"] for a in hits], ["a2", "a3"])

    def test_format_alpha_card_contains_chinese_labels(self):
        alpha = {
            "id": "a9",
            "status": "ACTIVE",
            "dateCreated": "2026-06-27T09:00:00-04:00",
            "dateSubmitted": "2026-06-28T09:00:00+08:00",
            "settings": {
                "region": "USA",
                "universe": "TOP3000",
                "delay": 1,
                "decay": 12,
                "neutralization": "INDUSTRY",
                "truncation": 0.08,
            },
            "regular": {"code": "expr9"},
            "is": {"fitness": 1.92, "sharpe": 2.39, "turnover": 0.165, "selfCorrelation": 0.6675},
        }

        card = format_alpha_card(alpha)

        self.assertIn("时间", card)
        self.assertIn("创建时间", card)
        self.assertIn("2026-06-27", card)
        self.assertIn("因子", card)
        self.assertIn("状态", card)
        self.assertIn("提交状态", card)
        self.assertIn("Fitness", card)
        self.assertIn("Sharpe", card)

    def test_format_alpha_card_uses_real_alpha_timestamp_not_current_clock(self):
        alpha = {
            "id": "a10",
            "status": "ACTIVE",
            "dateCreated": "2024-01-02T03:04:05-04:00",
            "dateSubmitted": None,
            "settings": {
                "region": "USA",
                "universe": "TOP3000",
                "delay": 1,
                "decay": 2,
                "neutralization": "INDUSTRY",
                "truncation": 0.08,
            },
            "regular": {"code": "expr10"},
            "is": {"fitness": 1.55, "sharpe": 1.66, "turnover": 0.12},
        }

        card = format_alpha_card(alpha)

        self.assertIn("2024-01-02", card)
        self.assertNotIn("北京时间", card)

    def test_build_summary_lines_groups_quality_and_submit_status(self):
        alphas = [
            {"id": "a1", "is": {"fitness": 1.6, "sharpe": 1.1}, "status": "ACTIVE", "dateSubmitted": "2026-06-28T09:00:00+08:00"},
            {"id": "a2", "is": {"fitness": 1.9, "sharpe": 1.7}, "status": "FAILED", "dateSubmitted": None},
            {"id": "a3", "is": {"fitness": 1.1, "sharpe": 1.0}, "status": "ACTIVE", "dateSubmitted": None},
        ]

        lines = build_summary_lines(alphas, threshold=1.5)

        self.assertIn("命中因子: 3", lines)
        self.assertIn("官方已提交: 1", lines)
        self.assertIn("未见官方提交: 2", lines)
        self.assertIn("Fitness>=1.5: 2", lines)
        self.assertIn("Fitness<1.5: 1", lines)

    def test_extract_metrics_requires_real_submission_evidence(self):
        metrics = extract_metrics(
            {
                "id": "a1",
                "status": "ACTIVE",
                "dateSubmitted": None,
                "is": {"fitness": 1.8, "sharpe": 1.5},
            }
        )

        self.assertFalse(metrics["submit_passed"])

    def test_build_offline_summary_lines_explains_missing_credentials(self):
        lines = build_offline_summary_lines()

        self.assertEqual(len(lines), 3)

    def test_build_project_summary_lines_reports_runtime_status(self):
        lines = build_project_summary_lines(
            {
                "status": "RUNNING",
                "project_health": "HEALTHY",
                "mode": "research+submit",
                "cycle_count": 4,
                "last_leaf_job": "submit_batch",
                "submission_summary": {
                    "submitted_active": 2,
                    "submitted_pending": 1,
                    "skipped": 3,
                    "request_errors": 0,
                    "total": 6,
                },
                "submit_status": "degraded",
                "submit_failure_kind": "mixed_partial_success",
                "last_error": "",
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("RUNNING", rendered)
        self.assertIn("research+submit", rendered)
        self.assertIn("submit_batch", rendered)
        self.assertIn("项目健康: 正常", rendered)
        self.assertIn("Submit摘要", rendered)
        self.assertIn("ACTIVE 2", rendered)
        self.assertIn("Submit治理", rendered)
        self.assertIn("degraded", rendered)
        self.assertIn("mixed_partial_success", rendered)

    def test_build_project_summary_lines_translates_booting_progress_to_chinese_runtime_stage(self):
        lines = build_project_summary_lines(
            {
                "status": "BOOTING",
                "project_health": "正常",
                "mode": "research",
                "cycle_count": 0,
                "last_leaf_job": "evolve_skill_preview",
                "last_progress": "stage: fetch_pnl | 413/10000",
                "last_error": "",
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("运行中", rendered)
        self.assertIn("正在抓取 PnL", rendered)
        self.assertIn("413/10000", rendered)
        self.assertIn("4.13%", rendered)

    def test_build_adapter_summary_lines_renders_chain_level_truth_when_available(self):
        lines = build_adapter_summary_lines(
            {
                "adapter_status": "RUNNING",
                "authority_map": {
                    "project_runtime_state": "authority",
                    "batch_submit_results": "authority",
                    "project_runtime_log": "authority",
                    "adapter_state": "derived",
                    "panel_state": "display_only",
                },
                "workflow_verdicts": {
                    "research_chain": {"state": "partial", "summary": "研究快照工作流运行中"},
                    "submit_chain": {"state": "complete", "summary": "固定模板提交治理链可用"},
                    "production_chain": {"state": "broken", "summary": "新因子生产链未接入"},
                    "truth_closure_chain": {"state": "partial", "summary": "研究记忆真相未闭合"},
                },
                "next_attention": "runtime 仅编排研究快照脚本和固定模板 submit 脚本",
            }
        )

        rendered = "\n".join(lines)
        self.assertIn("新因子生产链未接入", rendered)
        self.assertIn("研究快照工作流运行中", rendered)
        self.assertIn("truth_closure_chain", rendered)


if __name__ == "__main__":
    unittest.main()
