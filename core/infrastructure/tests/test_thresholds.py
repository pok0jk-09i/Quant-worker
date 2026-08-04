"""Red-phase tests for sub_universe_sharpe_threshold (P0 Story 1).

Run: python -m pytest core/infrastructure/tests/test_thresholds.py
These tests are written BEFORE the implementation exists (test-first).
They assert the verified formula + invariants from team/BRAIN_THRESHOLDS_VERIFIED.md.
"""

from __future__ import annotations

import math
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from hypothesis import given, settings, strategies as st  # noqa: E402

from core.infrastructure import thresholds as T  # noqa: E402


class TestSubUniverseSharpeThreshold(unittest.TestCase):
    def test_d1_ratio_half(self):
        # SQRT252 * max(0.065, 0.5*0.15) = 15.8745 * 0.075 ≈ 1.1906
        got = T.sub_universe_sharpe_threshold(sub_size=500, largest_universe_size=1000, delay=1)
        self.assertAlmostEqual(got, math.sqrt(252) * 0.075, places=4)

    def test_d0_higher_coeff(self):
        # SQRT252 * max(0.065, 0.5*0.25) = 15.8745 * 0.125 ≈ 1.9843
        got = T.sub_universe_sharpe_threshold(sub_size=500, largest_universe_size=1000, delay=0)
        self.assertAlmostEqual(got, math.sqrt(252) * 0.125, places=4)

    def test_small_sub_universe_uses_absolute_floor(self):
        # ratio = 0.01 -> 0.01*0.15 = 0.0015 < 0.065 -> max -> 0.065
        got = T.sub_universe_sharpe_threshold(sub_size=10, largest_universe_size=1000, delay=1)
        self.assertAlmostEqual(got, math.sqrt(252) * 0.065, places=4)

    def test_ratio_clamped_to_one(self):
        # ratio = 2.0 -> clamped to 1.0 -> SQRT252 * 0.15
        got = T.sub_universe_sharpe_threshold(sub_size=2000, largest_universe_size=1000, delay=1)
        self.assertAlmostEqual(got, math.sqrt(252) * 0.15, places=4)

    def test_default_delay_is_d1(self):
        a = T.sub_universe_sharpe_threshold(sub_size=500, largest_universe_size=1000)
        b = T.sub_universe_sharpe_threshold(sub_size=500, largest_universe_size=1000, delay=1)
        self.assertEqual(a, b)


class TestSubUniverseInvariantsPropertyBased(unittest.TestCase):
    """Hypothesis PBT: invariants must hold for all valid inputs (not just hand-picked)."""

    @given(
        sub_size=st.integers(min_value=1, max_value=10_000),
        largest=st.integers(min_value=1, max_value=10_000),
        delay=st.integers(min_value=0, max_value=1),
    )
    @settings(max_examples=500, deadline=None)
    def test_invariants(self, sub_size, largest, delay):
        floor = T.sub_universe_sharpe_threshold(
            sub_size=sub_size, largest_universe_size=largest, delay=delay)
        coeff = 0.15 if delay == 1 else 0.25
        ratio = min(1.0, sub_size / largest)
        expected = math.sqrt(252) * max(0.065, ratio * coeff)
        # 1) matches verified formula
        self.assertAlmostEqual(floor, expected, places=9)
        # 2) absolute floor respected
        self.assertGreaterEqual(floor, math.sqrt(252) * 0.065 - 1e-9)
        # 3) finite and positive
        self.assertTrue(math.isfinite(floor) and floor > 0)
        # 4) delay=0 floor >= delay=1 floor at same ratio
        floor_d1 = T.sub_universe_sharpe_threshold(
            sub_size=sub_size, largest_universe_size=largest, delay=1)
        if delay == 0:
            self.assertGreaterEqual(floor, floor_d1 - 1e-9)

    @given(
        s1=st.integers(min_value=1, max_value=5000),
        s2=st.integers(min_value=1, max_value=5000),
        largest=st.integers(min_value=1, max_value=5000),
    )
    @settings(max_examples=300, deadline=None)
    def test_monotone_non_decreasing_in_ratio(self, s1, s2, largest):
        # floor does not decrease as sub_size grows (ratio increases)
        f1 = T.sub_universe_sharpe_threshold(sub_size=s1, largest_universe_size=largest, delay=1)
        f2 = T.sub_universe_sharpe_threshold(sub_size=s2, largest_universe_size=largest, delay=1)
        if s1 <= s2:
            self.assertLessEqual(f1, f2 + 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
