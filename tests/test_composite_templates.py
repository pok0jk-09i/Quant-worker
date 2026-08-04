"""F block tests — composite alphas with adaptive (BRAIN-IS) weighting."""
import re

import pytest

from scripts.composite_templates import (
    build_composite,
    normalize_weights,
    adaptive_weights,
    iter_composite_expressions,
)


def test_normalize_weights_sums_to_one():
    assert abs(sum(normalize_weights([0.5, 0.5])) - 1.0) < 1e-9
    assert abs(sum(normalize_weights([0.4, 0.4, 0.2])) - 1.0) < 1e-9


def test_build_composite_wraps_each_signal_and_weights():
    expr = build_composite(["(high + low) / 2 - close",
                             "-ts_zscore(enterprise_value/ebitda, 63)"])
    assert expr.startswith("0.50*(")
    assert " + 0.50*(" in expr
    # each sub-signal rank-wrapped exactly once (no rank(rank())
    assert "rank(rank(" not in expr
    nums = [float(x) for x in re.findall(r"(\d+\.\d+)\*", expr)]
    assert abs(sum(nums) - 1.0) < 1e-9


def test_build_composite_requires_two_signals():
    with pytest.raises(ValueError):
        build_composite(["close"])


def test_adaptive_weights_uses_feedback():
    base = [0.5, 0.5]
    # no feedback -> equal normalized
    assert adaptive_weights(["mean_reversion_price", "value_quality"], base, None) == [0.5, 0.5]
    # feedback favoring value_quality -> its weight grows
    fb = {"available": True, "family_mean": {
        "mean_reversion_price": {"mean": 0.2, "n": 3},
        "value_quality": {"mean": 1.5, "n": 3},
    }}
    aw = adaptive_weights(["mean_reversion_price", "value_quality"], base, fb)
    assert aw[1] > aw[0]
    assert abs(sum(aw) - 1.0) < 1e-9


def test_iter_composite_expressions_yields_valid():
    for _name, expr, _hyp in iter_composite_expressions():
        assert expr.startswith("0.")
        assert "rank(" in expr
        assert "+" in expr
        assert "rank(rank(" not in expr
