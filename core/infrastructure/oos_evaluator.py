"""OOS / holdout overfitting evaluator (P0 Story 2).

The gate against blind IS-only submission. Threshold ``max_decay_ratio=0.50``
is cross-validated (3 independent sources):

  - backtrex: "a performance degradation factor above 50% between IS and OOS
    is a critical warning sign"
  - mathandmarkets: "Expect a 30-50% haircut" (IS Sharpe 1.0 -> honest OOS
    0.5-0.7)
  - CFM (Capital Fund Management) paper "Why and how systematic strategies
    decay": published factors' Sharpe declines by about half out-of-sample.

Design choice (STDD Article II): only a *verified* threshold is allowed to
hard-block. When OOS data is missing we return a DIAGNOSTIC (passed=True,
no block) so we never invent a gate on absent data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OosResult:
    passed: bool
    decay_ratio: float | None
    is_sharpe: float | None
    oos_sharpe: float | None
    reasons: list[str] = field(default_factory=list)


# Verified critical-warning line for IS->OOS Sharpe decay.
MAX_DECAY_RATIO = 0.50


def evaluate_oos(
    *,
    is_sharpe: float | None,
    oos_sharpe: float | None,
    max_decay_ratio: float = MAX_DECAY_RATIO,
) -> OosResult:
    """Evaluate in-sample -> out-of-sample Sharpe decay.

    Rules (threshold cross-validated):
      - ``oos_sharpe is None``  -> passed=True, diagnostic only (no data).
      - ``oos_sharpe < 0``      -> passed=False (clearly broken).
      - ``decay = (is - oos) / is``; ``decay > max_decay_ratio`` -> passed=False.
      - otherwise               -> passed=True.

    ``max_decay_ratio`` is configurable; the default 0.50 is verified, not
    guessed.
    """
    if oos_sharpe is None:
        return OosResult(
            passed=True, decay_ratio=None, is_sharpe=is_sharpe,
            oos_sharpe=None, reasons=["no OOS data: diagnostic only"])

    if oos_sharpe < 0:
        return OosResult(
            passed=False, decay_ratio=None, is_sharpe=is_sharpe,
            oos_sharpe=oos_sharpe, reasons=[f"OOS Sharpe {oos_sharpe} < 0"])

    if is_sharpe in (None, 0):
        # No IS baseline to compute decay; OOS>0 is acceptable (diagnostic).
        return OosResult(
            passed=True, decay_ratio=None, is_sharpe=is_sharpe,
            oos_sharpe=oos_sharpe,
            reasons=["OOS positive but no IS baseline: diagnostic only"])

    decay = (is_sharpe - oos_sharpe) / is_sharpe
    if decay > max_decay_ratio:
        return OosResult(
            passed=False, decay_ratio=decay, is_sharpe=is_sharpe,
            oos_sharpe=oos_sharpe,
            reasons=[f"OOS decay {decay:.2f} > {max_decay_ratio:.2f}"])

    return OosResult(
        passed=True, decay_ratio=decay, is_sharpe=is_sharpe,
        oos_sharpe=oos_sharpe, reasons=[])
