"""Sub-universe Sharpe absolute floor (P0 Story 1).

Formula verified by Quant Researcher (cross-validated, 2 independent sources):
  Oo_Amy_oO https://blog.csdn.net/Oo_Amy_oO/article/details/147725000
  zread     https://zread.ai/Miasyster/QuantGPT/14-wq-brain-simulation-and-submission

Supersedes the discarded `0.75 * sqrt(sub/uni) * alpha_sharpe` formula
(structurally wrong: relative scaling instead of absolute floor).

    floor = SQRT252 * max(0.065, ratio * coeff)
    coeff = 0.15 if delay == 1 else 0.25
    ratio = clamp(sub_size / largest_universe_size, 0 < ratio <= 1)
"""

from __future__ import annotations

import math

SQRT252 = math.sqrt(252)  # ≈ 15.8745

# Coefficients per BRAIN delay. D0 requires a higher floor than D1.
_DELAY_COEFF = {1: 0.15, 0: 0.25}

# Absolute floor (applies when the sub-universe is tiny). Verified constant.
ABSOLUTE_FLOOR = 0.065


def sub_universe_sharpe_threshold(
    *,
    sub_size: int,
    largest_universe_size: int,
    delay: int = 1,
) -> float:
    """Return the absolute Sharpe floor for the sub-universe check.

    Parameters
    ----------
    sub_size:
        Number of instruments in the alpha's sub-universe.
    largest_universe_size:
        Size of the largest (parent) universe this sub-universe belongs to.
    delay:
        BRAIN delay (1 = D1, 0 = D0). D0 uses a stricter coefficient.

    Returns
    -------
    float
        ``SQRT252 * max(ABSOLUTE_FLOOR, ratio * coeff)`` where
        ``ratio = min(1.0, sub_size / largest_universe_size)`` (clamped to
        (0, 1] so a degenerate or inverted ratio can never produce a
        negative/zero floor).
    """
    if sub_size is None or largest_universe_size is None:
        raise ValueError("sub_size and largest_universe_size are required")
    if sub_size <= 0 or largest_universe_size <= 0:
        raise ValueError("sub_size and largest_universe_size must be positive")

    coeff = _DELAY_COEFF.get(delay, _DELAY_COEFF[1])
    ratio = sub_size / largest_universe_size
    if ratio > 1.0:
        ratio = 1.0
    # ratio is > 0 here (both inputs positive), so no zero/neg floor.
    return SQRT252 * max(ABSOLUTE_FLOOR, ratio * coeff)
