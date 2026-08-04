"""Red-phase tests for OOS overfitting evaluator (P0 Story 2).

Threshold (max_decay_ratio=0.50) is cross-validated:
  - backtrex: "degradation factor above 50% between IS and OOS is a critical warning"
  - mathandmarkets: "Expect a 30-50% haircut"
  - CFM paper: published factors' Sharpe decays by ~half
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from core.infrastructure import oos_evaluator as oe  # noqa: E402


class TestEvaluateOos(unittest.TestCase):
    def test_decay_over_50_fails(self):
        r = oe.evaluate_oos(is_sharpe=2.0, oos_sharpe=0.8)  # decay 0.6
        self.assertFalse(r.passed)
        self.assertAlmostEqual(r.decay_ratio, 0.6, places=6)
        self.assertTrue(any("0.60" in reason for reason in r.reasons))

    def test_oos_negative_fails(self):
        r = oe.evaluate_oos(is_sharpe=1.5, oos_sharpe=-0.2)
        self.assertFalse(r.passed)
        self.assertTrue(any("OOS Sharpe" in reason and "< 0" in reason
                            for reason in r.reasons))

    def test_healthy_decay_passes(self):
        r = oe.evaluate_oos(is_sharpe=2.0, oos_sharpe=1.3)  # decay 0.35
        self.assertTrue(r.passed)
        self.assertAlmostEqual(r.decay_ratio, 0.35, places=6)

    def test_missing_oos_is_diagnostic_not_block(self):
        r = oe.evaluate_oos(is_sharpe=1.6, oos_sharpe=None)
        self.assertTrue(r.passed)
        self.assertIsNone(r.decay_ratio)
        self.assertTrue(any("diagnostic" in reason for reason in r.reasons))

    def test_custom_threshold(self):
        # with a stricter 0.30 cap, decay 0.35 now fails
        r = oe.evaluate_oos(is_sharpe=2.0, oos_sharpe=1.3, max_decay_ratio=0.30)
        self.assertFalse(r.passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
