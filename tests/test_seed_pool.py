# STORY: S-p1a-seedpool (Gen-4 门① coverage for P1A/SEEDPOOL)
"""Tests for core/infrastructure/seed_pool.py — the first gated deliverable.

Covers 门② (unit + integration + PBT) and provides the GWT-referencing test
that 门① (gate_spec) checks for.  Run: python -m pytest tests/test_seed_pool.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hypothesis import given, settings, strategies as st  # noqa: E402

from core.infrastructure.seed_pool import (  # noqa: E402
    build_real_parent_pool,
    classify_style_family,
    deflated_sharpe_gate,
    deflated_sharpe_ratio,
    is_timeout_prone_refined,
    iter_real_unsubmitted,
    load_alpha_db,
    PoolRecord,
    real_self_corr_gate,
    spectral_diversity_filter,
    structural_corr,
    to_candidate_dict,
    STYLE_FAMILIES,
    _style_balance,
)


# ── synthetic db helpers ──────────────────────────────────────────────────────
def _rec(status, fitness, expr, **kw):
    return {
        "status": status, "fitness": fitness, "sharpe": kw.get("sharpe", fitness),
        "turnover": kw.get("turnover", 0.2), "expression": expr,
        "settings": {"region": "USA", "universe": "TOP3000", "decay": 4,
                     "neutralization": "SUBINDUSTRY", "truncation": 0.01},
        "region": "USA", "universe": "TOP3000",
        **({"oos_metrics": kw["oos"]} if kw.get("oos") else {}),
    }


def _db(records):
    return {"alphas": {str(i): r for i, r in enumerate(records)}}


# ── 门② unit tests ─────────────────────────────────────────────────────────────
def test_iter_real_unsubmitted_excludes_ghost_active():
    db = _db([
        _rec("ACTIVE", 1.9, "rank(close)"),                       # ghost (platform-absent)
        _rec("UNSUBMITTED", 1.3, "-ts_mean(returns, 33)"),        # real, safe
        _rec("UNSUBMITTED", 0.8, "volume / adv20"),               # below floor
        _rec("UNSUBMITTED", 1.2, "anl46_eps_revision"),           # real safe analyst field (A21: anl46_)
    ])
    out = iter_real_unsubmitted(db, fitness_min=1.0)
    exprs = {r["expression"] for r in out}
    assert "rank(close)" not in exprs                      # ghost ACTIVE excluded
    assert "-ts_mean(returns, 33)" in exprs
    assert "anl46_eps_revision" in exprs                   # real analyst field kept (A21)
    assert "volume / adv20" not in exprs                  # below fitness floor


def test_is_timeout_prone_refined_field_level():
    # A21 (research-verified): the REAL analyst/news prefix is anl46_ and is SAFE.
    # The sparse subfields anl4_/pv13_/_guidance stall BRAIN at ~35% and are BLOCKED.
    assert is_timeout_prone_refined("anl46_eps_revision") is False        # real safe analyst field
    assert is_timeout_prone_refined("anl4_eps_revision") is True          # sparse analyst subfield blocked
    assert is_timeout_prone_refined("pv13_price_momentum") is True        # sparse graph subfield blocked
    assert is_timeout_prone_refined("ts_corr(-ts_mean(returns,5), anl4_sparse_ghost, 20)") is True  # sparse
    assert is_timeout_prone_refined("close - open") is False              # safe primitive


def test_classify_style_family():
    assert classify_style_family("-ts_mean(returns, 33)") == "reversal"
    assert classify_style_family("-ts_zscore(enterprise_value / ebitda, 63)") == "value_quality"
    assert classify_style_family("volume / adv20") == "liquidity"
    assert classify_style_family("-ts_std_dev(returns, 20)") == "low_volatility"
    assert classify_style_family("anl46_eps_revision - ts_mean(returns,5)") == "news_sentiment"
    assert classify_style_family("(high + low) / 2 - close") in STYLE_FAMILIES


def test_structural_corr_and_diversity_filter():
    a = PoolRecord("(high + low) / 2 - close", {}, "t", "reversal", "h")
    b = PoolRecord("(high + low) / 2 - close", {}, "t", "reversal", "h")  # identical
    c = PoolRecord("-ts_mean(returns, 33)", {}, "t", "reversal", "h")     # different
    assert abs(structural_corr(a.expression, b.expression) - 1.0) < 1e-9
    assert structural_corr(a.expression, c.expression) < 1.0
    out = spectral_diversity_filter([a, b, c], per_cluster_cap=2)
    # a,b identical -> cluster of 2 kept (==cap); c distinct kept => 3
    assert len(out) == 3
    # with cap=1, identical pair collapses to 1
    out1 = spectral_diversity_filter([a, b, c], per_cluster_cap=1)
    assert len(out1) == 2


def test_real_self_corr_gate_with_exemption():
    pool = ["-ts_mean(returns, 33)", "volume / adv20"]
    # identical to an existing expr -> blocked
    assert real_self_corr_gate("-ts_mean(returns, 33)", pool) is False
    # borderline correlation but high sharpe -> exemption passes
    assert real_self_corr_gate("-ts_mean(returns, 33)", pool, exempt_sharpe=2.0) is True
    # distinct expr -> passes
    assert real_self_corr_gate("(high + low) / 2 - close", pool) is True


def test_deflated_sharpe():
    # With enough observations, a strong sharpe is certified (DSR -> 1.0).
    assert deflated_sharpe_ratio(2.0, 504) > 0.95
    assert deflated_sharpe_gate(2.0, 504) is True
    # Without n_obs, diagnostic pass (do not invent a gate on absent data).
    assert deflated_sharpe_gate(1.5, None) is True
    # Tiny sample -> even a decent sharpe is NOT certified (DSR < 0.95 => gate
    # fails).  DSR is mathematically correct: n=5, sharpe=1.5 (normal) => ~0.82.
    assert deflated_sharpe_ratio(1.5, 5) < 0.95
    assert deflated_sharpe_gate(1.5, 5) is False


def test_style_balance_quota():
    recs = [PoolRecord("e", {}, "t", fam, "h") for fam in
            (["reversal"] * 10 + ["liquidity"] * 2)]
    out = _style_balance(recs, per_family_quota=0.30)
    rev = [r for r in out if r.family == "reversal"]
    # pool size 12, cap = round(0.30*12)=4 -> reversal capped to 4
    assert len(rev) == 4


def test_build_real_parent_pool_excludes_ghost_and_balances():
    db = _db([
        _rec("ACTIVE", 1.9, "rank(close)"),                          # ghost
        _rec("UNSUBMITTED", 1.4, "-ts_mean(returns, 33)"),           # reversal
        _rec("UNSUBMITTED", 1.5, "-ts_zscore(enterprise_value/ebitda,63)"),  # value
        _rec("UNSUBMITTED", 1.3, "volume / adv20"),                  # liquidity
        _rec("UNSUBMITTED", 1.2, "-ts_std_dev(returns, 20)"),        # low_vol
        _rec("UNSUBMITTED", 1.6, "anl46_eps_revision"),               # news (A21 real field kept)
    ])
    res = build_real_parent_pool(db, fitness_min=1.0, per_family_quota=0.30)
    # ghost ACTIVE never enters any tier
    all_exprs = [r.expression for r in res["tier0"] + res["tier1"] + res["tier2"]]
    assert "rank(close)" not in all_exprs
    # tier0 has 5 families
    assert len(res["tier0"]) == 5
    # tier1 only UNSUBMITTED real material
    assert all(r.source == "tier1_real" for r in res["tier1"])
    # meta sanity
    assert res["meta"]["ghost_active_excluded"] is True
    assert res["meta"]["oos_by_construction"] is True
    # pool families are a subset of STYLE_FAMILIES
    assert set(res["meta"]["families"]) <= set(STYLE_FAMILIES)
    # to_candidate_dict satisfies the consumer contract shape
    cd = to_candidate_dict(res["pool"][0])
    assert isinstance(cd["expression"], str) and isinstance(cd["settings"], dict)


def test_build_real_parent_pool_real_db():
    """Integration: real 14MB alpha_db — Tier1 must surface real material, no ghost."""
    db = load_alpha_db()
    res = build_real_parent_pool(db, fitness_min=1.0)
    assert res["meta"]["tier1_count_raw"] > 0, "expected real UNSUBMITTED material"
    # none of the 10 ghost ACTIVE expressions should be in tier1
    active_exprs = {
        a.get("expression") for a in db["alphas"].values() if a.get("status") == "ACTIVE"
    }
    tier1_exprs = {r.expression for r in res["tier1"]}
    assert active_exprs.isdisjoint(tier1_exprs)


# ── 门② PBT (hypothesis): config-validity invariant ───────────────────────────
@settings(max_examples=30)
@given(
    fitness_min=st.floats(min_value=0.0, max_value=2.0),
    quota=st.floats(min_value=0.05, max_value=0.95),
    n=st.integers(min_value=0, max_value=8),
)
def test_build_pool_invariants_pbt(fitness_min, quota, n):
    recs = []
    families = ["-ts_mean(returns, 33)", "-ts_zscore(enterprise_value/ebitda,63)",
                "volume / adv20", "-ts_std_dev(returns, 20)"]
    for i in range(n):
        recs.append(_rec("UNSUBMITTED", max(0.0, fitness_min) + (i % 3) * 0.1,
                         families[i % len(families)]))
    db = _db(recs)
    res = build_real_parent_pool(db, fitness_min=fitness_min, per_family_quota=quota)
    # families always a subset of the canonical set
    assert set(res["meta"]["families"]) <= set(STYLE_FAMILIES)
    # pool never larger than the three tiers combined
    assert res["meta"]["pool_count"] <= (res["meta"]["tier0_count"]
                                         + res["meta"]["tier1_count_raw"]
                                         + res["meta"]["tier2_count"])
    # every pool record is a valid PoolRecord with required fields
    for r in res["pool"]:
        assert isinstance(r, PoolRecord)
        assert r.family in STYLE_FAMILIES
