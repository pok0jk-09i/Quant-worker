"""Tests for core.infrastructure.expression_types.

Uses REAL field ids from the BRAIN reference (industry/sector = GROUP,
cusip = SYMBOL, close/returns = MATRIX) plus the event-*named* field that
triggered BRAIN "event input" rejections.  The goal: prove the validator
catches the exact incompatibilities we observed in production logs
(Unit[Group:1] and event-input errors) while passing legitimate alphas.
"""

import sys
from pathlib import Path

import pytest

# Make project root importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import expression_types as et  # noqa: E402


@pytest.fixture(scope="module")
def field_types():
    return et.load_field_types()


def test_group_field_into_ts_operator_is_flagged(field_types):
    # pv13_*_sector / industry are GROUP (Unit[Group]) -> illegal in ts_corr
    expr = "ts_corr(industry, industry, 5)"
    v = et.validate_expression(expr, field_types)
    assert v, f"expected violation for {expr}, got empty"
    assert any("industry" in x and "ts_corr" in x for x in v)


def test_symbol_field_into_ts_operator_is_flagged(field_types):
    # cusip is SYMBOL -> illegal in ts_zscore
    expr = "ts_zscore(cusip, 60)"
    v = et.validate_expression(expr, field_types)
    assert v, f"expected violation for {expr}, got empty"
    assert any("cusip" in x for x in v)


def test_event_named_field_into_ts_backfill_is_flagged():
    # Event-*named* field triggers BRAIN "does not support event inputs".
    # Caught by heuristic pattern even if absent from the type map.
    expr = "ts_backfill(fnd6_newqeventv110_glceeps12, 120)"
    v = et.validate_expression(expr, et.load_field_types())
    assert v, f"expected event violation for {expr}, got empty"
    assert any("EVENT" in x or "newqevent" in x for x in v)


def test_group_field_in_arithmetic_is_flagged(field_types):
    # industry (GROUP) divided by close (MATRIX) -> divide needs numeric
    expr = "0.5 * rank(-(industry / close - 1))"
    v = et.validate_expression(expr, field_types)
    assert v, f"expected violation for {expr}, got empty"
    assert any("industry" in x and ("divide" in x or "/") for x in v) or any(
        "industry" in x for x in v
    )


def test_legit_alpha_passes(field_types):
    good = [
        "ts_mean(close, 20)",
        "rank(-returns)",
        "group_rank(ts_rank(close, 20), industry)",
        "group_zscore(-inverse(ts_backfill(close, 120)), industry)",
        "trade_when(greater(ts_mean(close, 3), 0), rank(-returns), -1)",
        "0.5 * rank(-(close / volume - 1)) + 0.5 * rank(ts_rank(fnd6_optlife, 60))",
    ]
    for expr in good:
        assert et.validate_expression(expr, field_types) == [], (
            f"legit alpha wrongly flagged: {expr} -> "
            f"{et.validate_expression(expr, field_types)}"
        )


def test_real_production_error_expression_flagged(field_types):
    # Verbatim from candidate_submit_results.json (Unit[Group:1] error)
    expr = (
        "trade_when(greater(ts_mean(ts_corr(pv13_hierarchy_min51_f3_513_sector,"
        "pv13_hierarchy_min20_f3_513_sector,5),3),0.85), rank(-returns), -1)"
    )
    v = et.validate_expression(expr, field_types)
    assert v, "expected violation for real prod expr, got empty"
    assert any("GROUP" in x or "pv13" in x for x in v)


def test_degrade_without_field_types():
    # Missing type map must never block -- returns [].
    assert et.validate_expression("ts_corr(industry, industry, 5)", {}) == []
    # None loads the real map; cusip (SYMBOL) is then correctly flagged.
    assert et.validate_expression("ts_zscore(cusip, 60)", None) != []


def test_parse_calls_handles_nesting():
    calls = et.parse_calls("group_rank(ts_rank(close, 20), industry)")
    ops = {c[0] for c in calls}
    assert "group_rank" in ops and "ts_rank" in ops
    # group_rank should see its two args intact
    grp = [c for c in calls if c[0] == "group_rank"][0]
    assert grp[1][0].strip() == "ts_rank(close, 20)"
    assert grp[1][1].strip() == "industry"
