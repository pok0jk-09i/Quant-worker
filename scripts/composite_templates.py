"""F block — composite alphas with adaptive weighting (AlphaSAGE + Kakushadze).

AlphaSAGE (ICLR 2026): "Dynamic Linear Combination ... re-weights [diverse
alphas] using simple linear regression" to compile a mega-alpha that adapts to
regime shifts while staying interpretable.  Kakushadze (arXiv 1603.05937):
for large N without binary clustering, Sharpe maximisation reduces to a
(weighted) regression — the key is combining LOW-CORRELATED alphas.  Real
BRAIN composites (QuantGPT / jglazar) confirm the golden recipe: 2+ rank()-wrapped
sub-signals summed.  Hubble adds the red line: linearly combining UNRELATED
alphas (3A1+4A2) does NOT diversify — combination must draw DISTINCT economic
families.

So F builds composites from DISTINCT D-template families (low correlation by
construction), wraps each sub-signal in rank(), and weights them ADAPTIVELY
from real BRAIN IS feedback (E block) — never by lowering the submission bar.
"""
from __future__ import annotations

import re

from scripts.economic_templates import ECONOMIC_TEMPLATES

# Composite recipes: each pairs DISTINCT economic families (low correlation).
COMPOSITE_RECIPES = [
    {"name": "reversion_value", "families": ["mean_reversion_price", "value_quality"],
     "weights": [0.5, 0.5]},
    {"name": "reversion_liquidity", "families": ["short_term_reversal", "liquidity_activity"],
     "weights": [0.5, 0.5]},
    {"name": "vol_value", "families": ["low_volatility", "value_quality"],
     "weights": [0.5, 0.5]},
    {"name": "momentum_liquidity", "families": ["debt_momentum_composite", "liquidity_activity"],
     "weights": [0.5, 0.5]},
    {"name": "reversion_vol", "families": ["vwap_deviation_reversal", "low_volatility"],
     "weights": [0.5, 0.5]},
    {"name": "triple_rev_val_liq",
     "families": ["mean_reversion_price", "value_quality", "liquidity_activity"],
     "weights": [0.4, 0.4, 0.2]},
]

# rank-safe wrap (replicated to keep this module decoupled from the generator).
_RANK_SAFE_OPS = {"rank", "zscore", "scale", "group_rank", "group_zscore", "sign"}


def _top_op(expr: str):
    m = re.match(r"^[+\-]?\s*([A-Za-z_]\w*)\s*\(", expr.strip())
    if m:
        return m.group(1)
    m2 = re.match(r"^[+\-]?\s*([A-Za-z_]\w*)", expr.strip())
    return m2.group(1) if m2 else None


def _safe_rank_wrap(expr: str) -> str:
    op = _top_op(expr)
    if op in _RANK_SAFE_OPS:
        return expr.strip()
    return f"rank({expr.strip()})"


def normalize_weights(weights) -> list[float]:
    total = sum(weights)
    if total <= 0:
        n = len(weights)
        return [round(1.0 / n, 2) for _ in range(n)]
    norm = [w / total for w in weights]
    rounded = [round(x, 2) for x in norm]
    diff = round(1.0 - sum(rounded), 2)
    rounded[-1] = round(rounded[-1] + diff, 2)
    return rounded


def build_composite(signals: list[str], weights=None) -> str:
    """Combine 2+ raw sub-signals into a weighted, rank-wrapped composite.

    Each signal is wrapped in rank() (idempotent if already safe) — the golden
    BRAIN recipe.  Weights are normalized to sum to 1.  Returns e.g.
    ``0.50*rank((high+low)/2-close) + 0.50*rank(-ts_zscore(EV/ebitda,63))``.
    """
    if len(signals) < 2:
        raise ValueError("composite requires >=2 sub-signals")
    ws = (normalize_weights(weights)
          if weights else normalize_weights([1] * len(signals)))
    parts = []
    for w, sig in zip(ws, signals):
        w_sig = _safe_rank_wrap(sig)
        # Parenthesise the weighted sub-signal: a sub-signal may itself be a
        # sum of ranks (e.g. a D composite "-rank(a) + rank(b)"), and without
        # parens "0.5*-rank(a) + rank(b)" would bind * only to the first term
        # (operator precedence) — silently dropping the intended weight.
        parts.append(f"{w:.2f}*({w_sig})")
    return " + ".join(parts)


def adaptive_weights(families: list[str], base_weights, feedback_bias) -> list[float]:
    """Up-weight families that BRAIN's IS feedback scored higher (E block).

    Degradation-first: no feedback / no family signal -> return base (normalized).
    Boosts a family's base weight by (1 + max(0, mean_sharpe)) so empirically
    stronger families dominate the composite — adaptive, grounded in real IS.
    """
    norm = normalize_weights(base_weights)
    if not feedback_bias or not feedback_bias.get("available"):
        return norm
    fam_mean = feedback_bias.get("family_mean") or {}
    if not fam_mean:
        return norm
    boosted = []
    for fam, w in zip(families, norm):
        info = fam_mean.get(fam)
        score = info.get("mean", 0.0) if isinstance(info, dict) else 0.0
        boosted.append(w * (1.0 + max(0.0, float(score))))
    return normalize_weights(boosted)


def iter_composite_expressions(feedback_bias=None):
    """Yield (name, composite_expression, hypothesis) for each recipe."""
    for recipe in COMPOSITE_RECIPES:
        fams = recipe["families"]
        sigs = []
        for f in fams:
            meta = ECONOMIC_TEMPLATES.get(f)
            if not meta:
                break
            sigs.append(meta["build"]())
        if len(sigs) != len(fams):
            continue
        ws = adaptive_weights(fams, recipe["weights"], feedback_bias)
        expr = build_composite(sigs, ws)
        hyp = (f"Composite of distinct families {fams} (cross-family low "
               f"correlation); adaptive weights {ws} from BRAIN IS feedback.")
        yield recipe["name"], expr, hyp
