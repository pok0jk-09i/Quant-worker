"""Tests for the E block — BRAIN IS feedback bias (test-first, 2026-08-02).

The feedback loop must learn from SIMULATION is_metrics (returned by BRAIN for
every COMPLETE sim), NOT by submitting low-quality alphas.  These tests pin
that behaviour and the degradation-first contract.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import brain_feedback as fb  # noqa: E402


def _entry(expr, sharpe, fitness=1.0, decay=4, truncation=0.01,
           neutralization="SUBINDUSTRY", region="USA", universe="TOP3000",
           status="COMPLETE"):
    return {
        "sim": {"status": status},
        "is_metrics": {"sharpe": sharpe, "fitness": fitness, "turnover": 0.1},
        "candidate": {
            "expression": expr,
            "settings": {
                "decay": decay, "truncation": truncation,
                "neutralization": neutralization, "region": region,
                "universe": universe,
            },
        },
    }


def test_extract_operators():
    assert set(fb.extract_operators("rank(ts_zscore(close, 20))")) == {
        "rank", "ts_zscore"}
    # operator nested inside trade_when
    ops = fb.extract_operators(
        "trade_when(ts_zscore(volume,60)>2, group_zscore(-close), -1)")
    assert {"trade_when", "ts_zscore", "group_zscore"} <= set(ops)


def test_extract_fields():
    fields = fb.extract_fields("rank(ts_corr(close, volume, 20))")
    assert "close" in fields and "volume" in fields
    # operator names must NOT appear as fields
    assert "rank" not in fields and "ts_corr" not in fields
    # numeric constants excluded
    assert "20" not in fields


def test_build_feedback_bias_aggregates_per_feature(tmp_path):
    results = [
        _entry("rank(ts_zscore(close, 20))", sharpe=2.0, decay=4, truncation=0.01),
        _entry("rank(ts_zscore(close, 20))", sharpe=1.8, decay=4, truncation=0.01),
        _entry("rank(ts_corr(volume, open, 10))", sharpe=-0.5, decay=8, truncation=0.04),
    ]
    p = tmp_path / "results.json"
    p.write_text(json.dumps(results), encoding="utf-8")
    bias = fb.build_feedback_bias(p)
    assert bias["available"] is True
    assert bias["n_samples"] == 3
    # decay=4 scored higher than decay=8
    assert bias["preferred_decay"] == 4
    # truncation=0.01 scored higher than 0.04
    assert bias["preferred_truncation"] == 0.01
    # close appears in 2 high entries -> top field
    assert "close" in bias["top_fields"]
    # best recipe is the 2.0 one
    assert bias["top_recipes"][0]["score"] == 2.0


def test_build_feedback_bias_skips_non_complete_and_missing_metrics(tmp_path):
    results = [
        # TIMEOUT -> skipped
        _entry("rank(close)", sharpe=2.0, status="TIMEOUT"),
        # COMPLETE but no is_metrics -> skipped
        {"sim": {"status": "COMPLETE"},
         "candidate": {"expression": "rank(volume)",
                       "settings": {"decay": 4, "truncation": 0.01,
                                    "neutralization": "SUBINDUSTRY"}}},
        # COMPLETE with is_metrics -> counted
        _entry("rank(open)", sharpe=3.0, status="COMPLETE"),
    ]
    p = tmp_path / "results.json"
    p.write_text(json.dumps(results), encoding="utf-8")
    bias = fb.build_feedback_bias(p)
    # only the COMPLETE entry with is_metrics counts (rank(open), sharpe=3.0)
    assert bias["n_samples"] == 1
    assert bias["best_score"] == 3.0


def test_build_feedback_bias_handles_missing_or_malformed(tmp_path):
    missing = tmp_path / "nope.json"
    assert fb.build_feedback_bias(missing)["available"] is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert fb.build_feedback_bias(bad)["available"] is False
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps([]), encoding="utf-8")
    assert fb.build_feedback_bias(empty)["available"] is False


def test_apply_feedback_bias_no_feedback_returns_unchanged():
    base = {"decay": 4, "truncation": 0.01, "neutralization": "SUBINDUSTRY"}
    assert fb.apply_feedback_bias(base, None) == base
    assert fb.apply_feedback_bias(base, {"available": False}) == base


def test_apply_feedback_bias_nudges_params():
    base = {"decay": 4, "truncation": 0.01, "neutralization": "SUBINDUSTRY"}
    fbias = {"available": True, "preferred_decay": 8,
             "preferred_truncation": 0.04, "preferred_neutralization": "INDUSTRY"}
    out = fb.apply_feedback_bias(base, fbias)
    assert out["decay"] == 8
    assert out["truncation"] == 0.04
    assert out["neutralization"] == "INDUSTRY"
    # original dict untouched
    assert base["decay"] == 4


def test_apply_feedback_bias_ignores_partial_preference():
    base = {"decay": 4, "truncation": 0.01, "neutralization": "SUBINDUSTRY"}
    fbias = {"available": True, "preferred_decay": 8}  # no truncation/neut
    out = fb.apply_feedback_bias(base, fbias)
    assert out["decay"] == 8
    assert out["truncation"] == 0.01  # unchanged
    assert out["neutralization"] == "SUBINDUSTRY"  # unchanged
