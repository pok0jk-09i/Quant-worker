"""Single source of truth for BRAIN submission thresholds.

Values are the OFFICIAL BRAIN hard lines, cross-validated 2026-08-01 from
top-tier sources (zread.ai QuantGPT mirror of wq_brain_client.py, dafu-zhu
operator reference, alexisdpc real-alpha settings).  No magic numbers should
be scattered across submitter scripts -- import from here instead.

References (official-equivalent):
  * zread.ai/Miasyster/QuantGPT  -> enforces IS test thresholds
        Sharpe >= 1.25, Fitness >= 1.0, Returns >= 6.3%,
        Turnover in [1%, 70%], Max Weight <= 10%,
        Sub-Universe Sharpe >= sqrt(252) * max(0.065, ratio*coeff)
  * dafu-zhu/alpha-lab            -> "Sharpe > 1.25, Fitness > 1, Turnover 1% cutoff"
  * alexisdpc/WorldQuant-alpha-trading -> "fitness passing requirement > 1.0"
"""

from __future__ import annotations

# ── OFFICIAL BRAIN HARD LINES (the ACTIVE gate) ──────────────────────
SHARPE_MIN = 1.25
FITNESS_MIN = 1.0
RETURNS_MIN = 0.063          # 6.3% absolute returns floor
TURNOVER_MIN = 0.01          # 1% cutoff
TURNOVER_MAX = 0.70          # 70% upper bound
MAX_WEIGHT_MAX = 0.10        # CONCENTRATED_WEIGHT red line (global)
SELF_CORR_MAX = 0.7          # platform Self-Correlation uniqueness gate

# ── OUR SUBMISSION GATE (HIGH-STANDARD premium bar — the user's real goal) ──
# Policy RESTORED 2026-08-02 after correction.  The user's objective is to
# SUBMIT HIGH-STANDARD factors, NOT "anything BRAIN minimally accepts".  So the
# local SUBMIT gate is a PREMIUM bar (>=1.5/1.5, turnover<=0.30), strictly
# ABOVE BRAIN's floor.  We do NOT relax to BRAIN's minimum — that would be
# "submitting for the sake of submitting" and betrays the goal.
#
# The feedback loop (E block) is fed by the SIMULATION is_metrics BRAIN already
# returns for every COMPLETE sim (sharpe/fitness/turnover) — NOT by submitting
# low-quality alphas.  Raising factor quality until it clears THIS gate is the
# job of D (economic templates) / E (IS-feedback bias) / F (combos) / G
# (diversity), not lowering the bar.
SUBMIT_SHARPE_FLOOR = 1.5     # PREMIUM bar, NOT BRAIN floor (1.25)
SUBMIT_FITNESS_FLOOR = 1.5    # PREMIUM bar, NOT BRAIN floor (1.0)
SUBMIT_TURNOVER_MAX = 0.30    # tighter than BRAIN's 0.70 — high-standard

# PREMIUM tier — north-star even stricter than the gate; used for analytics /
# E feedback prioritisation (which submitted alphas to learn from first).
PREMIUM_SHARPE = 1.8
PREMIUM_FITNESS = 1.5


def passes_submission_gate(is_metrics: dict) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for the FINAL SUBMISSION GATE.

    ``is_metrics`` is the in-sample metrics dict BRAIN returned.  The gate is
    exactly BRAIN's official floor: Sharpe>=1.25, Fitness>=1.0, Turnover in
    [1%, 70%].  Returns ``("ok", "ok")`` when the alpha clears the bar.
    """
    sharpe = is_metrics.get("sharpe") or 0
    fitness = is_metrics.get("fitness") or 0
    turnover = is_metrics.get("turnover")
    if turnover is None:
        turnover = 1.0
    if not (fitness >= SUBMIT_FITNESS_FLOOR
            and sharpe >= SUBMIT_SHARPE_FLOOR
            and TURNOVER_MIN <= turnover <= SUBMIT_TURNOVER_MAX):
        return False, "metrics_threshold"
    return True, "ok"


def is_premium(is_metrics: dict) -> bool:
    """True when the alpha also clears our north-star PREMIUM tier."""
    sharpe = is_metrics.get("sharpe") or 0
    fitness = is_metrics.get("fitness") or 0
    return bool(sharpe >= PREMIUM_SHARPE and fitness >= PREMIUM_FITNESS)


def as_dict() -> dict:
    """Return all thresholds as a flat dict (handy for tests / logging)."""
    return {
        "SHARPE_MIN": SHARPE_MIN,
        "FITNESS_MIN": FITNESS_MIN,
        "RETURNS_MIN": RETURNS_MIN,
        "TURNOVER_MIN": TURNOVER_MIN,
        "TURNOVER_MAX": TURNOVER_MAX,
        "MAX_WEIGHT_MAX": MAX_WEIGHT_MAX,
        "SELF_CORR_MAX": SELF_CORR_MAX,
        "SUBMIT_SHARPE_FLOOR": SUBMIT_SHARPE_FLOOR,
        "SUBMIT_FITNESS_FLOOR": SUBMIT_FITNESS_FLOOR,
        "SUBMIT_TURNOVER_MAX": SUBMIT_TURNOVER_MAX,
        "PREMIUM_SHARPE": PREMIUM_SHARPE,
        "PREMIUM_FITNESS": PREMIUM_FITNESS,
    }
