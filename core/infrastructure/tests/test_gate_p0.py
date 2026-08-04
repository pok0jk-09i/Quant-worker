"""Red-phase integration tests: P0 changes wired into submit_gate.

- Story 1: IND/TOP500 sub_universe_sharpe_min 0.0漏洞 replaced by dynamic formula floor.
- Story 2: OOS evaluator blocks overfit alphas inside the gate.
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from core.infrastructure import submit_gate as sg  # noqa: E402
import math  # noqa: E402


class TestGateSubUniverseFloor(unittest.TestCase):
    def test_ind_blocked_when_sub_sharpe_below_formula_floor(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"}]
        metrics = {"sub_universe_sharpe": 1.0}  # floor for ratio 0.5 D1 ≈ 1.19
        res = sg.gate_submission(
            region="IND", universe="TOP500", is_checks=checks, is_metrics=metrics,
            sub_size=500, largest_universe_size=1000, delay=1)
        self.assertFalse(res.submit_allowed)
        self.assertTrue(any("sub_universe_sharpe" in r for r in res.reasons))

    def test_ind_allowed_when_sub_sharpe_meets_floor(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"}]
        floor = math.sqrt(252) * 0.075  # ratio 0.5 D1
        metrics = {"sub_universe_sharpe": floor + 0.1}
        res = sg.gate_submission(
            region="IND", universe="TOP500", is_checks=checks, is_metrics=metrics,
            sub_size=500, largest_universe_size=1000, delay=1)
        self.assertTrue(res.submit_allowed)

    def test_small_sub_universe_uses_absolute_floor(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"}]
        metrics = {"sub_universe_sharpe": 1.0}  # floor for ratio 0.01 = 15.87*0.065≈1.03
        res = sg.gate_submission(
            region="IND", universe="TOP500", is_checks=checks, is_metrics=metrics,
            sub_size=10, largest_universe_size=1000, delay=1)
        self.assertFalse(res.submit_allowed)


class TestRegionConcentrationFloor(unittest.TestCase):
    """P1 hardening: the region concentration floor must read the numeric
    CONCENTRATED_WEIGHT value from is.checks (BRAIN does NOT expose a flat
    `concentrated_weight` key in the `is` metrics dict — only inside
    is.checks as CONCENTRATED_WEIGHT value=0.5). The old code read
    is_metrics.get('concentrated_weight') which is always None -> the
    region floor was dead code (only the generic hard-check caught FAIL).

    Regression: a PASS-but-over-cap check must still be blocked by the
    region floor (hard-check sees PASS and would let it through).
    """

    def test_ind_concentration_blocked_from_checks_value(self):
        # result PASS but value 0.5 >> 0.1 cap -> region floor must block.
        checks = [
            {"name": "LOW_SHARPE", "result": "PASS"},
            {"name": "CONCENTRATED_WEIGHT", "result": "PASS", "value": 0.5},
        ]
        res = sg.gate_submission(
            region="IND", universe="TOP500", is_checks=checks, is_metrics={})
        self.assertFalse(res.submit_allowed)
        self.assertTrue(
            any("CONCENTRATED_WEIGHT" in r for r in res.reasons),
            f"expected CONCENTRATED_WEIGHT reason, got {res.reasons}",
        )

    def test_ind_concentration_ok_when_under_cap(self):
        checks = [
            {"name": "LOW_SHARPE", "result": "PASS"},
            {"name": "CONCENTRATED_WEIGHT", "result": "PASS", "value": 0.05},
        ]
        res = sg.gate_submission(
            region="IND", universe="TOP500", is_checks=checks, is_metrics={})
        self.assertTrue(res.submit_allowed)

    def test_region_floor_reads_checks_param_directly(self):
        # evaluate_region_floors must accept is_checks and extract the value.
        reasons = sg.evaluate_region_floors(
            region="IND", universe="TOP500", is_metrics={},
            is_checks=[{"name": "CONCENTRATED_WEIGHT", "result": "PASS", "value": 0.5}])
        self.assertTrue(
            any("CONCENTRATED_WEIGHT" in r for r in reasons),
            f"expected CONCENTRATED_WEIGHT reason, got {reasons}",
        )


class TestGateOosIntegration(unittest.TestCase):
    def test_oos_fail_blocks_submission(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"}]
        res = sg.gate_submission(
            region="USA", universe="TOP3000", is_checks=checks,
            is_sharpe=2.0, oos_sharpe=0.8)  # decay 0.6 -> fail
        self.assertFalse(res.submit_allowed)
        self.assertIsNotNone(res.oos)
        self.assertFalse(res.oos.passed)
        self.assertTrue(any("oos" in r.lower() for r in res.reasons))

    def test_oos_missing_is_diagnostic_allows(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"}]
        res = sg.gate_submission(
            region="USA", universe="TOP3000", is_checks=checks,
            is_sharpe=1.6, oos_sharpe=None)
        self.assertTrue(res.submit_allowed)
        self.assertIsNotNone(res.oos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
