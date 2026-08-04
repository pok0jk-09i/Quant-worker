"""Tests for the FINAL SUBMISSION GATE — HIGH-STANDARD premium bar.

CORRECTION 2026-08-02: the user's objective is to SUBMIT HIGH-STANDARD
factors, not "anything BRAIN minimally accepts".  The local SUBMIT gate is a
PREMIUM bar (>=1.5/1.5, turnover<=0.30), strictly ABOVE BRAIN's floor
(1.25/1.0/[1%,70%]).  We deliberately do NOT relax to BRAIN's minimum.

The feedback loop (E) is fed by SIMULATION is_metrics (returned by BRAIN for
every COMPLETE sim), NOT by submitting low-quality alphas.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import thresholds_config as cfg  # noqa: E402


def _m(sharpe, fitness, turnover):
    return {"sharpe": sharpe, "fitness": fitness, "turnover": turnover}


def test_submit_gate_is_strictly_above_brain_floor():
    # The whole point: our bar is HIGHER than BRAIN's minimum, not equal to it.
    assert cfg.SUBMIT_SHARPE_FLOOR > cfg.SHARPE_MIN
    assert cfg.SUBMIT_FITNESS_FLOOR > cfg.FITNESS_MIN
    assert cfg.SUBMIT_TURNOVER_MAX < cfg.TURNOVER_MAX


def test_gate_rejects_brain_floor_alpha():
    # An alpha that only clears BRAIN's floor must NOT pass our high bar.
    ok, reason = cfg.passes_submission_gate(_m(1.30, 1.10, 0.50))
    assert ok is False
    assert reason == "metrics_threshold"


def test_gate_blocks_below_floor():
    ok, reason = cfg.passes_submission_gate(_m(1.00, 0.90, 0.30))
    assert ok is False
    assert reason == "metrics_threshold"


def test_gate_accepts_high_standard():
    ok, reason = cfg.passes_submission_gate(_m(1.50, 1.50, 0.20))
    assert ok is True
    assert reason == "ok"


def test_gate_accepts_above_high_standard():
    ok, reason = cfg.passes_submission_gate(_m(2.10, 1.60, 0.20))
    assert ok is True
    assert reason == "ok"


def test_gate_turnover_band():
    # below 1% cutoff -> blocked
    assert cfg.passes_submission_gate(_m(2.0, 2.0, 0.005))[0] is False
    # above our 30% high-standard cap -> blocked (even if below BRAIN's 70%)
    assert cfg.passes_submission_gate(_m(2.0, 2.0, 0.45))[0] is False
    # inside our band -> ok
    assert cfg.passes_submission_gate(_m(1.6, 1.6, 0.25))[0] is True


def test_is_premium_tier():
    # premium tier is even stricter than the gate
    assert cfg.is_premium(_m(1.90, 1.60, 0.30)) is True
    assert cfg.is_premium(_m(1.60, 1.60, 0.30)) is False
    # negative sharpe never premium
    assert cfg.is_premium(_m(-1.0, 1.0, 0.30)) is False


def test_internal_floor_at_least_platform_minimum():
    # invariants the original suite pinned (inequalities still hold)
    assert cfg.SUBMIT_SHARPE_FLOOR >= cfg.SHARPE_MIN
    assert cfg.SUBMIT_FITNESS_FLOOR >= cfg.FITNESS_MIN
    assert cfg.SUBMIT_TURNOVER_MAX <= cfg.TURNOVER_MAX
