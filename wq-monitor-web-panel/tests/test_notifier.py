import unittest

from quant_worker_monitor_panel.notifier import (
    build_error_popup,
    build_factor_popup,
    build_offline_popup,
    collect_new_hit_ids,
    should_popup_for_error,
)


class NotifierTests(unittest.TestCase):
    def test_collect_new_hit_ids_only_returns_unseen_ids(self):
        current_hits = [
            {"id": "a1"},
            {"id": "a2"},
            {"id": "a3"},
        ]

        self.assertEqual(collect_new_hit_ids(current_hits, {"a2"}), {"a1", "a3"})

    def test_build_factor_popup_includes_factor_count_and_details(self):
        hits = [
            {"id": "a1", "status": "ACTIVE", "regular": {"code": "expr1"}, "is": {"fitness": 1.9, "sharpe": 1.7}},
            {"id": "a2", "status": "ACTIVE", "regular": {"code": "expr2"}, "is": {"fitness": 1.8, "sharpe": 1.6}},
        ]

        title, body = build_factor_popup(hits, threshold=1.5, max_preview=1)

        self.assertEqual(title, "Quant worker 因子提醒")
        self.assertIn("本次发现 2 个", body)
        self.assertIn("expr1", body)
        self.assertIn("还有 1 个因子未展示", body)

    def test_build_error_popup_includes_error_text(self):
        title, body = build_error_popup("认证失败: 401")

        self.assertEqual(title, "Quant worker 异常提醒")
        self.assertIn("认证失败: 401", body)

    def test_should_popup_for_error_changes_only_once(self):
        self.assertTrue(should_popup_for_error("认证失败: 401", None))
        self.assertFalse(should_popup_for_error("认证失败: 401", "认证失败: 401"))
        self.assertTrue(should_popup_for_error("认证失败: 429", "认证失败: 401"))

    def test_build_offline_popup_explains_missing_credentials(self):
        title, body = build_offline_popup()

        self.assertIn("离线运行", title)
        self.assertIn("未找到 BRAIN 凭据", body)


if __name__ == "__main__":
    unittest.main()
