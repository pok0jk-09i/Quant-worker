"""Region-aware pre-submission gate for BRAIN alphas.

THE PROBLEM
-----------
We wasted submission attempts (and burned quota) on alphas that BRAIN
rejects at the production-submit step with HTTP 403. Investigation showed
the rejections were NOT account/quota issues -- they were *region-specific
hard checks* that the local simulation never evaluated. Example: an IND
alpha fails ``CONCENTRATED_WEIGHT`` (limit 0.1, observed value 0.5) and
``CLUSTER_TEST`` (ERROR), yet the local gate only looked at USA-centric
metrics (LOW_SHARPE / CLUSTER_TEST / LOW_FITNESS / LOW_TURNOVER) and let
it through.

THE FIX (P0)
------------
Three defensive layers, all evaluated from data BRAIN already returns in
the alpha's ``is.checks`` / ``is`` metrics (zero extra API cost):

1. **Hard-check blocker (generic, region-agnostic).** If ANY check in
   ``is.checks`` has ``result in {FAIL, ERROR}``, the alpha is
   unsubmitable -- submitting guarantees a 403. Block it.
2. **Region minimum-metrics table.** Each region/universe has stricter
   floors on certain metrics (e.g. IND requires a concentration cap).
   We encode those floors and block when they are not met.
3. **Sub-universe Sharpe absolute floor (P0 Story 1).** For IND/TOP500 we
   now apply the *verified* formula ``SQRT252 * max(0.065, ratio*coeff)``
   instead of the old ``sub_universe_sharpe_min = 0.0`` no-op that let every
   IND factor slip through to a 403.
4. **OOS overfitting gate (P0 Story 2).** When IS/OOS Sharpe are supplied,
   block alphas whose OOS decay exceeds the cross-validated 50% line, or
   whose OOS Sharpe is negative. Missing OOS data is diagnostic only
   (never invent a gate on absent data -- STDD Article II).

The gate returns a structured :class:`GateResult` so the submitter can log
*why* an alpha was held back instead of blindly trying and failing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .thresholds import sub_universe_sharpe_threshold
from .oos_evaluator import evaluate_oos, OosResult


# Region/universe -> metric floors that BRAIN enforces as hard checks.
# Values are conservative floors derived from observed BRAIN rejections.
# Keys are "REGION/UNIVERSE" (universe optional -> applies to all).
REGION_METRIC_FLOORS: dict[str, dict[str, float]] = {
    # Non-USA regions carry a stricter concentration cap.
    "IND": {
        "concentrated_weight_max": 0.1,   # CONCENTRATED_WEIGHT limit
    },
    "IND/TOP500": {
        "concentrated_weight_max": 0.1,
    },
    # USA keeps the global floors already enforced by FITNESS/SHARPE gates.
    "USA": {},
}

# Regions that require the sub-universe Sharpe absolute-floor check (Story 1).
# Verified formula replaces the old sub_universe_sharpe_min=0.0 no-op.
SUB_UNIVERSE_FLOOR_REGIONS = {"IND", "IND/TOP500", "TOP500"}

# Nominal universe sizes (BRAIN: "TOP N = top N most liquid stocks",
# cross-validated 2026-08-01 via hr-23's official Settings mirror + zread.ai).
# Used as `largest_universe_size` for the √252 sub-universe formula. The real
# BRAIN sub-universe test splits the universe 50/50, so `sub_size` defaults to
# largest // 2 when not supplied by the caller (see universe_size helpers).
UNIVERSE_SIZE = {
    "TOP3000": 3000,
    "TOP2000": 2000,
    "TOP1000": 1000,
    "TOP500": 500,
    "TOP200": 200,
}


def largest_universe_size(universe: str | None) -> int | None:
    """Resolve the nominal size of a universe (or None if unknown)."""
    if not universe:
        return None
    return UNIVERSE_SIZE.get(universe.upper())


def default_sub_size(universe: str | None) -> int | None:
    """Sub-universe size used by BRAIN's 50/50 split (largest // 2)."""
    largest = largest_universe_size(universe)
    return largest // 2 if largest else None


def _find_check(
    is_checks: list[dict[str, Any]] | None,
    name_fragments: tuple[str, ...],
) -> dict[str, Any] | None:
    """Return the first is.checks entry whose name contains a fragment."""
    if not is_checks:
        return None
    for c in is_checks:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name", "")).upper()
        if any(frag.upper() in name for frag in name_fragments):
            return c
    return None


@dataclass
class GateResult:
    submit_allowed: bool
    reasons: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    oos: OosResult | None = None

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "ok"

    def __bool__(self) -> bool:
        return self.submit_allowed


def evaluate_hard_checks(is_checks: list[dict[str, Any]] | None) -> list[str]:
    """Return names of checks that are FAIL or ERROR (hard blockers)."""
    blocked: list[str] = []
    if not is_checks:
        return blocked
    for c in is_checks:
        if not isinstance(c, dict):
            continue
        result = str(c.get("result", "")).upper()
        name = c.get("name")
        if result in ("FAIL", "ERROR"):
            blocked.append(str(name) if name is not None else "?")
    return blocked


def evaluate_region_floors(
    region: str | None,
    universe: str | None,
    is_metrics: dict[str, Any] | None,
    *,
    is_checks: list[dict[str, Any]] | None = None,
    sub_size: int | None = None,
    largest_universe_size: int | None = None,
    delay: int = 1,
) -> list[str]:
    """Return human-readable reasons for failing region-specific floors."""
    if not region:
        return []
    is_metrics = is_metrics or {}
    reasons: list[str] = []

    floors = REGION_METRIC_FLOORS.get(f"{region}/{universe}")
    if floors is None:
        floors = REGION_METRIC_FLOORS.get(region, {})

    # Concentration cap (verified for IND/TOP500).
    # BRAIN does NOT expose a flat `concentrated_weight` key in the `is`
    # metrics dict -- the numeric value lives only inside is.checks as
    # CONCENTRATED_WEIGHT value=0.5. So we read it from is_metrics if
    # present, else fall back to extracting it from is.checks. This keeps
    # the floor alive even when is_metrics lacks the key (the previous bug
    # where is_metrics.get("concentrated_weight") was always None made this
    # floor dead code).
    cw = is_metrics.get("concentrated_weight")
    if cw is None and is_checks:
        for c in is_checks:
            if not isinstance(c, dict):
                continue
            if str(c.get("name", "")).upper() == "CONCENTRATED_WEIGHT":
                cw = c.get("value")
                break
    if "concentrated_weight_max" in floors and cw is not None:
        try:
            if float(cw) > float(floors["concentrated_weight_max"]):
                reasons.append(
                    f"CONCENTRATED_WEIGHT {cw} > {floors['concentrated_weight_max']}"
                )
        except (TypeError, ValueError):
            pass

    # Sub-universe Sharpe absolute floor (Story 1) -- P0 fix for the 0.0 no-op.
    # Two independent paths, both sourced from data BRAIN already returns:
    #   (a) BRAIN's own sub-universe check in is.checks (authoritative verdict).
    #   (b) Our √252 formula (cross-validated) when sizes + reported sharpe exist.
    if region in SUB_UNIVERSE_FLOOR_REGIONS:
        sub_check = _find_check(is_checks, ("SUB_UNIVERSE", "SUBUNIVERSE", "SUB_UNI"))
        if sub_check:
            res = str(sub_check.get("result", "")).upper()
            if res in ("FAIL", "ERROR"):
                reasons.append(f"SUB_UNIVERSE check {res}")

        if sub_size and largest_universe_size:
            try:
                floor = sub_universe_sharpe_threshold(
                    sub_size=sub_size,
                    largest_universe_size=largest_universe_size,
                    delay=delay,
                )
                val = (
                    is_metrics.get("sub_universe_sharpe")
                    or is_metrics.get("sub_sharpe")
                    or is_metrics.get("subuniverse_sharpe")
                )
                if val is not None and float(val) < float(floor):
                    reasons.append(
                        f"sub_universe_sharpe {val} < floor {floor:.4f}"
                    )
            except (TypeError, ValueError):
                pass
        # If sizes are missing we cannot verify the floor via (b) -> but (a)
        # may still have caught it. Diagnostic only, never invent a gate.

    return reasons


def gate_submission(
    *,
    region: str | None,
    universe: str | None,
    is_checks: list[dict[str, Any]] | None = None,
    is_metrics: dict[str, Any] | None = None,
    sub_size: int | None = None,
    largest_universe_size: int | None = None,
    delay: int = 1,
    is_sharpe: float | None = None,
    oos_sharpe: float | None = None,
) -> GateResult:
    """Decide whether an alpha may be submitted to BRAIN production.

    Parameters
    ----------
    region, universe:
        Alpha region/universe (e.g. "IND", "TOP500").
    is_checks:
        The ``is.checks`` array returned by BRAIN after simulation. Any
        FAIL/ERROR entry is a hard blocker.
    is_metrics:
        The ``is`` metrics dict (sharpe, fitness, concentrated_weight,
        sub_universe_sharpe, ...). Used for region floor checks.
    sub_size, largest_universe_size, delay:
        Sizes needed for the sub-universe Sharpe absolute-floor formula
        (Story 1). Required for IND/TOP500 to actually gate.
    is_sharpe, oos_sharpe:
        In-sample and out-of-sample Sharpe. When both (or OOS) are supplied,
        the OOS overfitting gate (Story 2) runs. Missing OOS is diagnostic.
    """
    failed = evaluate_hard_checks(is_checks)
    floor_reasons = evaluate_region_floors(
        region, universe, is_metrics, is_checks=is_checks,
        sub_size=sub_size, largest_universe_size=largest_universe_size, delay=delay)

    oos_result: OosResult | None = None
    oos_reasons: list[str] = []
    if is_sharpe is not None or oos_sharpe is not None:
        oos_result = evaluate_oos(is_sharpe=is_sharpe, oos_sharpe=oos_sharpe)
        if not oos_result.passed:
            oos_reasons.append(f"oos_fail:{' | '.join(oos_result.reasons)}")

    reasons: list[str] = []
    reasons.extend(f"hard_check_fail:{n}" for n in failed)
    reasons.extend(f"region_floor:{r}" for r in floor_reasons)
    reasons.extend(oos_reasons)

    return GateResult(
        submit_allowed=not (failed or floor_reasons or oos_reasons),
        reasons=reasons,
        failed_checks=failed,
        oos=oos_result,
    )
