"""G block — family-diversity gating (pillar ② DIVERSITY, Hubble family-aware).

Hubble (arXiv 2604.09601): "Family-aware selection: scoring and top-k selection
incorporate crowding, similarity, and factor-family concentration rather than
rewarding raw predictive statistics alone."  Empirically its top set was
dominated by range / volatility / trend families instead of crowded volume
templates.  Kakushadze 101: cross-family pairwise correlation is only 15.9%,
so spanning families is what buys diversification.

This module classifies a formulaic alpha into a canonical economic family and
enforces a per-family cap on the candidate pool so no single family crowds out
the rest — the family-aware analogue of Hubble's concentration penalty.
"""
from __future__ import annotations

import math
from collections import defaultdict

# Canonical economic families (aligned with Hubble range/vol/trend discovery
# + Kakushadze 101 economic taxonomy + our D template families).
FAMILIES = (
    "mean_reversion",
    "momentum",
    "volatility",
    "liquidity",
    "value_quality",
    "price_structure",
    "composite",
    "other",
)

# Map D-template family names -> canonical family.
D_FAMILY_TO_CANONICAL = {
    "mean_reversion_price": "mean_reversion",
    "short_term_reversal": "mean_reversion",
    "vwap_deviation_reversal": "mean_reversion",
    "volume_price_reversal": "mean_reversion",
    "debt_momentum_composite": "momentum",
    "value_quality": "value_quality",
    "liquidity_activity": "liquidity",
    "low_volatility": "volatility",
}

# Fundamental-field markers (value/quality family).
_FUNDAMENTAL = (
    "fnd", "enterprise_value", "ebitda", "debt/", "sales/", "/assets",
    "book_value", "earnings", "roa", "roe", "revenue", "cash_",
    "growth", "net_income", "operating_income", "equity",
)


def classify_family(expression: str) -> str:
    """Heuristically map a FASTEXPR alpha to a canonical economic family.

    Deterministic, ordered checklist.  Not a correctness-critical classifier —
    it drives the diversity GATE (which family is over-represented), so stable
    bucketing matters more than perfect economic taxonomy.
    """
    e = expression.lower()
    # 1) value / quality — fundamentals
    if any(tok in e for tok in _FUNDAMENTAL):
        return "value_quality"
    # 2) liquidity — volume / adv
    if "volume" in e or "adv" in e:
        return "liquidity"
    # 3) volatility — variance / std / abs returns
    if "ts_std_dev" in e or "ts_std" in e or "power(" in e or "abs(returns" in e:
        return "volatility"
    # 4) momentum / trend — time-series trend operators
    if any(op in e for op in ("ts_rank", "ts_delta", "ts_corr", "ts_av_diff",
                              "ts_decay_linear", "ts_decay_exp_window", "ts_backfill")):
        return "momentum"
    # 5) mean reversion — intraday average price / -ts_mean(returns)
    if "(high + low)" in e or "(high+low)" in e or "ts_mean(returns" in e or "(high+low)/2" in e:
        return "mean_reversion"
    # 6) price structure — vwap / open intraday
    if "vwap" in e or "open" in e:
        return "price_structure"
    return "other"


def family_of(candidate: dict) -> str:
    """Return the canonical family of a candidate dict, preferring an explicit
    ``family`` tag (D templates / composites) and falling back to expression
    classification for parent-pool variants."""
    fam = candidate.get("family")
    if isinstance(fam, str):
        if fam.startswith("composite"):
            return "composite"
        canon = D_FAMILY_TO_CANONICAL.get(fam)
        if canon:
            return canon
    return classify_family(candidate.get("expression", "") or "")


def enforce_family_diversity(candidates: list[dict], cap_ratio: float = 0.30) -> list[dict]:
    """Cap per-family representation so no single family crowds the pool.

    Hubble's family-aware selection penalises concentration; here we hard-cap
    each canonical family at ``ceil(cap_ratio * len(candidates))`` (minimum 2).
    Over-represented families are trimmed from the tail (lowest priority keeps
    earlier entries).  Order is otherwise preserved.  Returns a NEW list.
    """
    if not candidates:
        return []
    cap = max(2, math.ceil(cap_ratio * len(candidates)))
    kept_per: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    for c in candidates:
        fam = family_of(c)
        if kept_per[fam] >= cap:
            continue  # over cap -> drop (trim from tail)
        out.append(c)
        kept_per[fam] += 1
    return out
