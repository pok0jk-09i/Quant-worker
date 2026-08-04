"""G block tests — family-diversity gating (Hubble family-aware concentration cap)."""
from core.infrastructure.family_classifier import (
    classify_family,
    family_of,
    enforce_family_diversity,
    FAMILIES,
)
from scripts.economic_templates import iter_template_expressions


def test_classify_family_returns_known_family():
    for _fam, expr, _h in iter_template_expressions():
        c = classify_family(expr)
        assert c in FAMILIES, (expr, c)


def test_classify_family_specific():
    from scripts.economic_templates import (
        build_mean_reversion_price,
        build_value_quality,
        build_low_volatility,
        build_liquidity_activity,
        build_short_term_reversal,
    )
    assert classify_family(build_mean_reversion_price()) == "mean_reversion"
    assert classify_family(build_value_quality()) == "value_quality"
    assert classify_family(build_low_volatility()) == "volatility"
    assert classify_family(build_liquidity_activity()) == "liquidity"
    assert classify_family(build_short_term_reversal()) == "mean_reversion"


def test_family_of_prefers_explicit_family():
    c = {"family": "value_quality", "expression": "rank(close)"}
    assert family_of(c) == "value_quality"
    c2 = {"family": "composite:reversion_value", "expression": "x"}
    assert family_of(c2) == "composite"
    c3 = {"expression": "(high + low) / 2 - close"}
    assert family_of(c3) == "mean_reversion"


def test_enforce_family_diversity_caps_overrepresented():
    cands = []
    for i in range(30):
        cands.append({"expression": f"rank(-ts_mean(returns, {i + 2}))",
                      "family": "mean_reversion"})
    for i in range(10):
        cands.append({"expression": f"-ts_zscore(ebitda, {i + 2})",
                      "family": "value_quality"})
    out = enforce_family_diversity(cands, cap_ratio=0.5)
    # cap = ceil(0.5*40) = 20 -> mean_reversion trimmed to 20, value_quality kept 10
    counts = {}
    for c in out:
        f = family_of(c)
        counts[f] = counts.get(f, 0) + 1
    assert counts.get("mean_reversion", 0) <= 20
    assert counts.get("value_quality", 0) == 10
    assert len(out) == 30


def test_enforce_family_diversity_preserves_order_and_empty():
    assert enforce_family_diversity([]) == []
    cands = [{"expression": "(high+low)/2-close", "family": "mean_reversion_price"}
             for _ in range(3)]
    out = enforce_family_diversity(cands, cap_ratio=0.3)
    # cap = max(2, ceil(0.3*3)) = 2 -> 3 same-family trimmed to 2
    assert len(out) == 2
    assert all(family_of(c) == "mean_reversion" for c in out)
