"""Tests for R1: activation of the √252 Sub-Universe formula.

The formula lived as dead code because callers never passed sub_size /
largest_universe_size.  These tests pin the now-wired behaviour: the gate
must (a) compute the √252 floor and block when the reported sub-universe
Sharpe is below it, and (b) honour BRAIN's own SUB_UNIVERSE check in
is.checks.  When sizes are absent it stays diagnostic (never invents a gate).
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import submit_gate as sg  # noqa: E402


def test_universe_size_table():
    assert sg.largest_universe_size("TOP3000") == 3000
    assert sg.largest_universe_size("top500") == 500
    assert sg.largest_universe_size("TOP200") == 200
    assert sg.default_sub_size("TOP3000") == 1500  # 50/50 split
    assert sg.largest_universe_size("UNKNOWN") is None


def test_sub_universe_formula_blocks_below_floor():
    reasons = sg.evaluate_region_floors(
        "IND", "TOP500", {"sub_universe_sharpe": 0.5},
        sub_size=250, largest_universe_size=500, delay=1,
    )
    assert any("sub_universe_sharpe" in r for r in reasons), reasons


def test_sub_universe_formula_passes_above_floor():
    # 1.5 is well above the ~1.19 (delay1) floor for this ratio.
    reasons = sg.evaluate_region_floors(
        "IND", "TOP500", {"sub_universe_sharpe": 1.5},
        sub_size=250, largest_universe_size=500, delay=1,
    )
    assert not any("sub_universe_sharpe" in r for r in reasons), reasons


def test_sub_universe_check_fail_blocks():
    checks = [{"name": "SUB_UNIVERSE", "result": "FAIL", "value": 0.4, "limit": 1.0}]
    reasons = sg.evaluate_region_floors(
        "IND", "TOP500", {}, is_checks=checks,
        sub_size=250, largest_universe_size=500, delay=1,
    )
    assert any("SUB_UNIVERSE check" in r for r in reasons), reasons


def test_no_sizes_is_diagnostic_not_block():
    # Missing sizes -> formula path skipped; no check -> not blocked.
    reasons = sg.evaluate_region_floors("IND", "TOP500", {})
    assert reasons == []


def test_gate_submission_wires_formula():
    g = sg.gate_submission(
        region="IND", universe="TOP500",
        is_metrics={"sub_universe_sharpe": 0.5},
        sub_size=250, largest_universe_size=500, delay=1,
    )
    assert not g.submit_allowed
    assert any("sub_universe" in r.lower() for r in g.reasons), g.reasons


def test_non_floor_region_not_blocked_by_formula():
    # USA is not in SUB_UNIVERSE_FLOOR_REGIONS; formula must not fire.
    reasons = sg.evaluate_region_floors(
        "USA", "TOP3000", {"sub_universe_sharpe": 0.5},
        sub_size=1500, largest_universe_size=3000, delay=1,
    )
    assert not any("sub_universe_sharpe" in r for r in reasons), reasons
