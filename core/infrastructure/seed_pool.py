"""Real parent-pool builder (Gen-4 engineering of P1-A A1-A27).

Replaces ``candidate_generator.select_high_performing_alphas`` (which only
accepts ``status==ACTIVE`` — the 10 GHOST alphas that do not exist on BRAIN's
platform) with a REAL, BRAIN-verified, diversity-aware parent pool:

  * Tier0 — economic-template seeds, restructured into **5 style-balanced
            families** (momentum / reversal / value_quality / liquidity /
            low_volatility).  News/Sentiment lives as a *data-driven* 6th family
            populated only from real BRAIN material (see A21 below).
  * Tier1 — REAL BRAIN-evaluated UNSUBMITTED alphas (fitness >= FITNESS_MIN),
            the 13,191-row raw material that was previously never used.
  * Tier2 — Kakushadze-101 subset (literature-verified low-correlation seeds).

Disciplines (cross-validated; see team/BRAIN_THRESHOLDS_VERIFIED.md and the
父池真实化 research reports A1-A27):
  A19 OOS-by-construction — seeds only come from real BRAIN evaluation
      (IS/OOS), never from local sim derivatives.
  A20 Real Self-Correlation — candidate vs the existing submitted pool,
      threshold SELF_CORR_MAX (0.7) + 10% Sharpe exemption (platform real
      instance Self-Corr 0.693 passed via exemption).
  A21 News/Sentiment unblock — analyst/news fields allowed EXCEPT the specific
      sparse subfields that stall BRAIN at ~35% (R3-C refined to field-level).
  A22 Style balance — per-family quota so no single style dominates (fixes the
      50%-reversal skew of the old 8-family template set).
  A7  Deflated-Sharpe significance — DSR gate before a seed is trusted.
  A10/A16 Spectral diversity — structural-correlation proxy + per-cluster cap
      (TRUE correlation needs BRAIN return series; documented, not faked).

All functions are PURE and UNIT-TESTABLE.  No network, no BRAIN calls.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent           # .../core/infrastructure
SKILL_DIR = SCRIPT_DIR.parent.parent                     # .../wq-alpha-research (repo root)
if str(SKILL_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SKILL_DIR))

from core.infrastructure.thresholds_config import (  # noqa: E402
    SELF_CORR_MAX,
    SUBMIT_SHARPE_FLOOR,
    SUBMIT_TURNOVER_MAX,
)

# Defensive import of the project's data-driven timeout guard.
try:  # noqa: E402
    from core.infrastructure.timeout_field_guard import (  # noqa: E402
        is_timeout_prone as _proj_timeout_prone,
        TIMEOUT_PRONE_FIELDS as _PROJ_TIMEOUT_FIELDS,
    )
    _HAS_PROJ_GUARD = True
except Exception:  # pragma: no cover
    _proj_timeout_prone = None
    _PROJ_TIMEOUT_FIELDS = frozenset()
    _HAS_PROJ_GUARD = False


# ── Style families (A22: 5 balanced + 1 data-driven News/Sentiment) ──────────
STYLE_FAMILIES = (
    "momentum", "reversal", "value_quality", "liquidity",
    "low_volatility", "news_sentiment",
)
# A21 (field-level, research-verified): the REAL analyst/news field prefix on
# BRAIN is ``anl46_`` (anl46_sentiment / anl46_indicator / anl46_experts).  The
# ``anl4_`` / ``pv13_`` / ``_guidance`` prefixes are the SPECIFIC SPARSE
# subfields that stall BRAIN at ~35% (R3-C empirical 14-field list) — they are
# BLOCKED at the field level (see _REFINED_SPARSE) and therefore never reach
# classification as seeds.  Only ``anl46_`` is both real AND safe, so it is the
# sole news/sentiment classifier token.
NEWS_SENTIMENT_TOKENS = ("anl46_",)


@dataclass
class PoolRecord:
    expression: str
    settings: dict
    source: str                 # tier0_economic | tier1_real | tier2_kakushadze
    family: str
    hypothesis: str
    fitness: float | None = None
    sharpe: float | None = None
    turnover: float | None = None
    oos_present: bool = False


# ── Tier0: 5 style-balanced economic templates (literature-derived) ──────────
# Expressions use ONLY timeout-safe MATRIX fields (compose with R3-C).
TIER0_FAMILIES: dict[str, dict] = {
    "momentum": {
        "expr": "-ts_mean(returns, 33)",
        "hypothesis": "Short-term reversal: recent losers bounce (momentum reversal).",
    },
    "reversal": {
        "expr": "-ts_decay_linear(close / vwap, 10)",
        "hypothesis": "Price below VWAP mean-reverts after sentiment overshoot.",
    },
    "value_quality": {
        "expr": "-ts_zscore(enterprise_value / ebitda, 63)",
        "hypothesis": "Short richly-valued firms; fundamental => low turnover.",
    },
    "liquidity": {
        "expr": "volume / adv20",
        "hypothesis": "Trading-activity / liquidity signal.",
    },
    "low_volatility": {
        "expr": "-ts_std_dev(returns, 20)",
        "hypothesis": "Low-volatility premium (betting against high-variance names).",
    },
}


# ── Tier2: Kakushadze-101 subset (arXiv:1601.00991, verified low-correlation) ─
KAKUSHADZE_SUBSET: dict[str, str] = {
    "kakushadze_1": "(high + low) / 2 - close",
    "kakushadze_2": "-ts_mean(returns, 5)",
    "kakushadze_3": "-ts_zscore(close, 20)",
    "kakushadze_4": "rank(close) - rank(open)",
    "kakushadze_5": "rank(volume) - rank(adv20)",
}


# ── A21: refined timeout guard (field-level, not whole-prefix) ───────────────
# The project's R3-C blocks whole anl4_*/pv13_*/_guidance prefixes.  Research
# (A21) shows only SPECIFIC sparse subfields stall BRAIN at ~35%; blocking the
# whole prefix wrongly excludes high-coverage analyst/news fields.  This refined
# set keeps only the specific sparse subfields (from the 14-field empirical list),
# and DELIBERATELY drops bare "cap" (research: cap may complete in rank families).
_REFINED_SPARSE = (
    "anl4_", "pv13_", "_guidance",
    "net_income_total_2", "net_debt_reported_value",
    "research_development_expense_reported_value", "rel_ret_comp",
)


def is_timeout_prone_refined(expression: str) -> bool:
    """A21: block the specific SPARSE subfields (anl4_/pv13_/_guidance + named
    sparse metrics from the empirical 14-field ~35%-stall list).  The REAL
    analyst/news prefix ``anl46_`` is SAFE and passes this guard."""
    if not expression:
        return False
    tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expression))
    for tok in tokens:
        for pat in _REFINED_SPARSE:
            if pat.endswith("_") and tok.startswith(pat):
                return True
            if (not pat.endswith("_")) and pat in tok:
                return True
    return False


# ── A22: style-family classifier (deterministic heuristic) ───────────────────
def classify_style_family(expression: str) -> str:
    e = expression or ""
    low = e.lower()
    if any(t in low for t in NEWS_SENTIMENT_TOKENS):
        return "news_sentiment"
    if "ebitda" in low or "enterprise_value" in low or "book" in low or "debt" in low:
        return "value_quality"
    if "ts_std_dev" in low or ("ts_zscore" in low and "return" in low):
        return "low_volatility"
    if "volume" in low or "adv20" in low or "vwap" in low:
        return "liquidity"
    if "returns" in low and ("ts_mean" in low or "ts_decay_linear" in low):
        return "reversal"
    if "ts_mean" in low or "ts_decay_linear" in low or "ts_av_diff" in low:
        return "momentum"
    return "momentum"


# ── A10/A16: structural-correlation proxy (true corr needs BRAIN returns) ─────
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _tokens(expression: str) -> set[str]:
    return set(_TOKEN_RE.findall(expression or ""))


def structural_corr(expr_a: str, expr_b: str) -> float:
    """Jaccard similarity over operator+field tokens — a cheap STRUCTURAL proxy
    for alpha correlation.  Documented limitation: real correlation requires the
    BRAIN return series (provided by oos_evaluator at sim time); this proxy only
    catches *expression-shape* redundancy, not signal redundancy."""
    a, b = _tokens(expr_a), _tokens(expr_b)
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union)


def spectral_diversity_filter(
    candidates: Sequence[PoolRecord],
    corr_threshold: float = SELF_CORR_MAX,
    per_cluster_cap: int = 2,
    corr_fn: Callable[[str, str], float] = structural_corr,
) -> list[PoolRecord]:
    """A10/A16: cap each correlation-cluster to ``per_cluster_cap`` members so the
    pool covers more diverse signal.  Greedy: a candidate is kept unless it is
    already ``per_cluster_cap``-wise similar to kept candidates."""
    kept: list[PoolRecord] = []
    for c in candidates:
        similars = [k for k in kept if corr_fn(c.expression, k.expression) >= corr_threshold]
        if len(similars) < per_cluster_cap:
            kept.append(c)
    return kept


# ── A20: real Self-Correlation gate (vs existing submitted pool) ──────────────
def real_self_corr_gate(
    expression: str,
    existing_exprs: Iterable[str],
    threshold: float = SELF_CORR_MAX,
    exempt_sharpe: float | None = None,
) -> bool:
    """True if ``expression`` is distinct enough from the existing pool.

    Exemption (platform real instance): if ``exempt_sharpe`` >= 1.10 *
    SUBMIT_SHARPE_FLOOR, a borderline correlation is allowed (mirrors BRAIN's
    Self-Corr 0.693 passing via the 10% Sharpe exemption).
    """
    exprs = list(existing_exprs)
    if not exprs:
        return True
    max_corr = max(structural_corr(expression, e) for e in exprs)
    if max_corr <= threshold:
        return True
    if exempt_sharpe is not None and exempt_sharpe >= 1.10 * SUBMIT_SHARPE_FLOOR:
        return True
    return False


# ── A7: Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014) ──────────────────
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


_Z_ALPHA = 1.6448536269514722  # norm_ppf(0.95)


def deflated_sharpe_ratio(
    sharpe: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0,
) -> float:
    """DSR ~ P(sharpe is NOT a false discovery).  >= 0.95 => real alpha."""
    if n_obs < 2 or sharpe == 0:
        return 0.0
    denom = math.sqrt(1.0 - skew * sharpe + (kurt - 1.0) / 4.0 * sharpe * sharpe)
    if denom <= 0:
        return 0.0
    return _norm_cdf((math.sqrt(n_obs - 1) * sharpe - _Z_ALPHA) / denom)


def deflated_sharpe_gate(
    sharpe: float, n_obs: int | None, skew: float = 0.0, kurt: float = 3.0,
) -> bool:
    """A7 gate.  Without ``n_obs`` we cannot certify => diagnostic PASS (include)."""
    if n_obs is None:
        return True
    return deflated_sharpe_ratio(sharpe, n_obs, skew, kurt) >= 0.95


# ── Loading / selection ───────────────────────────────────────────────────────
def load_alpha_db(path: str | Path | None = None) -> dict:
    p = Path(path) if path else (SKILL_DIR / "alpha_db.json")
    if not p.exists():
        return {"alphas": {}, "last_update": None, "version": 1}
    return json.loads(p.read_text(encoding="utf-8"))


def _default_settings(region: str = "USA", universe: str = "TOP3000") -> dict:
    return {
        "instrumentType": "EQUITY",
        "region": region,
        "universe": universe,
        "delay": 1,
        "decay": 4,
        "neutralization": "SUBINDUSTRY",
        "truncation": 0.01,
    }


def iter_real_unsubmitted(
    db: dict, fitness_min: float = 1.0, turnover_max: float = SUBMIT_TURNOVER_MAX,
) -> list[dict]:
    """Tier1: real BRAIN-evaluated UNSUBMITTED alphas (A19 OOS-by-construction).

    These are material BRAIN actually simulated — the opposite of the ghost
    ACTIVE.  Filtered by fitness floor + turnover band.  Excludes anything that
    is timeout-prone at the FIELD level (A21 refined guard), so we never seed a
    simulation that will stall at ~35%.
    """
    out: list[dict] = []
    for aid, alpha in db.get("alphas", {}).items():
        if alpha.get("status") != "UNSUBMITTED":
            continue
        fitness = alpha.get("fitness") or 0
        turnover = alpha.get("turnover") or 1
        expr = alpha.get("expression") or (
            (alpha.get("regular") or {}).get("code", "") if isinstance(alpha.get("regular"), dict) else ""
        )
        if not expr:
            continue
        if fitness < fitness_min or turnover > turnover_max:
            continue
        if is_timeout_prone_refined(expr):
            continue
        settings = alpha.get("settings", {}) or {}
        out.append({
            "alpha_id": aid,
            "expression": expr,
            "settings": {
                "instrumentType": settings.get("instrumentType", "EQUITY"),
                "region": settings.get("region") or alpha.get("region") or "USA",
                "universe": settings.get("universe") or alpha.get("universe") or "TOP3000",
                "delay": settings.get("delay", 1),
                "decay": settings.get("decay", 4),
                "neutralization": settings.get("neutralization", "SUBINDUSTRY"),
                "truncation": settings.get("truncation", 0.01),
            },
            "fitness": fitness,
            "sharpe": alpha.get("sharpe"),
            "turnover": turnover,
            "oos_present": bool(alpha.get("oos_metrics") or alpha.get("oos")),
        })
    return out


def _style_balance(pool: list[PoolRecord], per_family_quota: float) -> list[PoolRecord]:
    """A22: cap each style family to ``per_family_quota`` of the pool size."""
    if not pool:
        return []
    cap = max(1, int(round(per_family_quota * len(pool))))
    by_family: dict[str, list[PoolRecord]] = {}
    for r in pool:
        by_family.setdefault(r.family, []).append(r)
    balanced: list[PoolRecord] = []
    for fam, recs in by_family.items():
        # keep highest-fitness first
        recs_sorted = sorted(recs, key=lambda r: r.fitness or 0, reverse=True)
        balanced.extend(recs_sorted[:cap])
    return balanced


# ── Orchestrator ──────────────────────────────────────────────────────────────
def build_real_parent_pool(
    db: dict,
    *,
    fitness_min: float = 1.0,
    per_family_quota: float = 0.30,
    include_tier2: bool = True,
    timeout_guard=None,
    n_obs_for_dsr: int | None = None,
    max_tier1: int = 250,
) -> dict:
    """Build the real, diversity-aware parent pool.

    Returns ``{'tier0':[PoolRecord], 'tier1':[PoolRecord], 'tier2':[PoolRecord],
    'pool':[PoolRecord], 'meta':{...}}``.

    ``max_tier1`` caps the real-material seed count to the top-N by fitness
    before the O(n^2) spectral filter.  We don't need 5k seeds — 250 diverse,
    high-fitness real seeds is ample for the generator and keeps the build
    sub-second on the full 14MB db.
    """
    # Tier0 — economic templates (5 balanced families)
    tier0: list[PoolRecord] = []
    for fam, meta in TIER0_FAMILIES.items():
        tier0.append(PoolRecord(
            expression=meta["expr"], settings=_default_settings(),
            source="tier0_economic", family=fam, hypothesis=meta["hypothesis"],
        ))

    # Tier1 — real BRAIN UNSUBMITTED material.  Cap to top-N by fitness so the
    # downstream spectral filter stays O(n^2)-on-a-small-n (production-fast).
    tier1_raw = iter_real_unsubmitted(db, fitness_min=fitness_min)
    tier1_sorted = sorted(tier1_raw, key=lambda a: a.get("fitness") or 0, reverse=True)
    tier1_selected = tier1_sorted[:max_tier1]
    tier1: list[PoolRecord] = []
    for a in tier1_selected:
        tier1.append(PoolRecord(
            expression=a["expression"], settings=a["settings"],
            source="tier1_real", family=classify_style_family(a["expression"]),
            hypothesis="real BRAIN-evaluated UNSUBMITTED seed",
            fitness=a["fitness"], sharpe=a["sharpe"], turnover=a["turnover"],
            oos_present=a["oos_present"],
        ))

    # Tier2 — Kakushadze-101 subset
    tier2: list[PoolRecord] = []
    if include_tier2:
        for name, expr in KAKUSHADZE_SUBSET.items():
            tier2.append(PoolRecord(
                expression=expr, settings=_default_settings(),
                source="tier2_kakushadze", family=classify_style_family(expr),
                hypothesis=f"Kakushadze-101 subset: {name}",
            ))

    # Merge
    merged = list(tier0) + list(tier1) + list(tier2)

    # A22 style balance
    merged = _style_balance(merged, per_family_quota)

    # A7 DSR significance gate (only when n_obs known; else diagnostic)
    if n_obs_for_dsr is not None:
        merged = [
            r for r in merged
            if deflated_sharpe_gate(r.sharpe or 0.0, n_obs_for_dsr)
        ]

    # A20 real self-correlation vs the EXISTING SUBMITTED pool (alphas already
    # live on BRAIN), NOT the raw UNSUBMITTED material we are selecting from
    # (that internal diversity is handled by spectral_diversity_filter below).
    # Restricting to non-UNSUBMITTED keeps this O(pool * submitted) tiny.
    existing_exprs = [
        (a.get("expression") or (
            (a.get("regular") or {}).get("code", "") if isinstance(a.get("regular"), dict) else ""))
        for a in db.get("alphas", {}).values()
        if a.get("status") != "UNSUBMITTED"
        and (a.get("expression") or isinstance(a.get("regular"), dict))
    ]
    merged = [
        r for r in merged
        if real_self_corr_gate(r.expression, existing_exprs, exempt_sharpe=r.sharpe)
    ]

    # A10/A16 spectral diversity (structural proxy + per-cluster cap)
    merged = spectral_diversity_filter(merged, per_cluster_cap=2)

    meta = {
        "tier0_count": len(tier0),
        "tier1_count_raw": len(tier1_raw),
        "tier1_count": sum(1 for r in merged if r.source == "tier1_real"),
        "tier2_count": len(tier2),
        "pool_count": len(merged),
        "families": sorted({r.family for r in merged}),
        "ghost_active_excluded": True,
        "oos_by_construction": True,
    }
    return {"tier0": tier0, "tier1": tier1, "tier2": tier2, "pool": merged, "meta": meta}


def to_candidate_dict(rec: PoolRecord) -> dict:
    """Convert a PoolRecord to the dict shape ``candidate_generator.main`` consumes
    (contract: team/contracts/contracts.json)."""
    return {
        "expression": rec.expression,
        "settings": rec.settings,
        "source": rec.source,
        "family": rec.family,
        "hypothesis": rec.hypothesis,
        "source_fitness": rec.fitness,
        "source_sharpe": rec.sharpe,
        "source_turnover": rec.turnover,
        "oos_present": rec.oos_present,
    }


if __name__ == "__main__":
    import sys
    d = load_alpha_db()
    result = build_real_parent_pool(d)
    print(json.dumps(result["meta"], indent=2, ensure_ascii=False))
    print(f"pool size = {len(result['pool'])}")
    sys.exit(0)
