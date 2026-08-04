"""Tests for P1-A (scope ABC): parameter hardening, rank-safe wrap, field preference.

These tests are written BEFORE the implementation (test-first, per STDD
discipline) and pin the acceptance criteria from
``P1A_DIRECTION_AND_PLAN_2026-08-02.md`` sections 3 (A/B/C) and 5 (GWT).

A — parameter hardening (truncation 0.01 first, decay default 4)
B — expression rank-safe wrap (_safe_rank_wrap)
C — field preference (avoid analyst / alternative-data fields in substitution)
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import expression_types as et  # noqa: E402
from scripts import candidate_generator as cg  # noqa: E402
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# A — 参数硬化
# ─────────────────────────────────────────────────────────────────────
def test_a1_truncation_options_has_0_01_first():
    """A1: 0.01 must be present and placed first (BRAIN达标alpha标配)."""
    assert 0.01 in cg.TRUNCATION_OPTIONS
    assert cg.TRUNCATION_OPTIONS[0] == 0.01


def test_a2_extract_settings_defaults():
    """A2: empty alpha -> truncation 0.01, decay 4, SUBINDUSTRY."""
    s = cg.extract_settings({})
    assert s["truncation"] == 0.01
    assert s["decay"] == 4
    assert s["neutralization"] == "SUBINDUSTRY"
    assert s["region"] == "USA"
    assert s["universe"] == "TOP3000"


def test_a2_extract_settings_inherits_parent_region():
    """Region/universe inherit from the parent alpha when present."""
    alpha = {"region": "IND", "universe": "TOP3000", "settings": {}}
    s = cg.extract_settings(alpha)
    assert s["region"] == "IND"
    assert s["universe"] == "TOP3000"


def test_a3_generate_variants_base_defaults():
    """A3: with base defaults, neutr-sweep variants carry truncation=0.01
    and no variant is missing truncation/decay keys."""
    base = cg.extract_settings({})  # truncation 0.01, decay 4
    variants = cg.generate_variants("rank(close)", base, max_variants=80)
    assert variants, "expected variants"
    neut = [v for v in variants if v["variant_type"].startswith("base:neut=")]
    assert neut, "expected neutralization-sweep variants"
    assert all(v["settings"]["truncation"] == 0.01 for v in neut)
    trunc_vals = {v["settings"]["truncation"] for v in variants}
    assert 0.01 in trunc_vals
    assert all(
        "truncation" in v["settings"] and "decay" in v["settings"]
        for v in variants
    )


# ─────────────────────────────────────────────────────────────────────
# B — rank 安全包裹
# ─────────────────────────────────────────────────────────────────────
def test_b_wrap_basic_operators():
    cases = [
        ("ts_corr(close, volume, 20)", "rank(ts_corr(close, volume, 20))"),
        ("log(close)", "rank(log(close))"),
        ("-ts_delta(close, 5)", "rank(-ts_delta(close, 5))"),
    ]
    for inp, exp in cases:
        assert cg._safe_rank_wrap(inp) == exp, inp


def test_b_wrap_trade_when_whole():
    inp = "trade_when(greater(volume, adv20), rank(-ts_delta(close, 5)), -1)"
    assert cg._safe_rank_wrap(inp) == f"rank({inp})"


def test_b_no_wrap_when_already_cross_sectional():
    for inp in [
        "rank(ts_corr(close, volume, 20))",
        "group_rank(ts_rank(close, 60), subindustry)",
        "zscore(close)",
        "sign(close)",
        "-rank(close)",
    ]:
        assert cg._safe_rank_wrap(inp) == inp, inp


def test_b_idempotent():
    for inp in ["ts_corr(close, volume, 20)", "rank(close)", "log(close)"]:
        once = cg._safe_rank_wrap(inp)
        twice = cg._safe_rank_wrap(once)
        assert once == twice


def test_b_wrap_preserves_type_safety():
    ft = et.load_field_types()
    exprs = [
        "ts_corr(close, volume, 20)",
        "log(close)",
        "-ts_delta(close, 5)",
        "trade_when(greater(volume, adv20), rank(-ts_delta(close, 5)), -1)",
    ]
    for e in exprs:
        wrapped = cg._safe_rank_wrap(e)
        assert et.is_type_safe(wrapped, ft), f"{wrapped} not type-safe"


@given(
    st.one_of(
        st.just("ts_corr(close, volume, 20)"),
        st.just("log(close)"),
        st.just("rank(close)"),
        st.just("group_rank(ts_rank(close, 60), subindustry)"),
        st.just("trade_when(greater(volume, adv20), rank(-ts_delta(close, 5)), -1)"),
        st.just("-ts_delta(close, 5)"),
    )
)
@settings(max_examples=200)
def test_b_pbt_idempotent_and_balanced(e):
    out = cg._safe_rank_wrap(e)
    # parens stay balanced
    depth = 0
    for ch in out:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        assert depth >= 0
    assert depth == 0
    # idempotent
    assert cg._safe_rank_wrap(out) == out


# ─────────────────────────────────────────────────────────────────────
# C — 字段偏好
# ─────────────────────────────────────────────────────────────────────
def test_c_is_analyst_or_alt():
    assert cg._is_analyst_or_alt("anl4_fs_detail_estimate")
    assert cg._is_analyst_or_alt("pv13_com_rk_au")
    assert cg._is_analyst_or_alt("max_book_value_per_share_guidance_2")
    assert not cg._is_analyst_or_alt("close")
    assert not cg._is_analyst_or_alt("volume")
    assert not cg._is_analyst_or_alt("cap")  # timeout-prone but not analyst


def test_c_prefer_non_analyst(monkeypatch):
    """When >=2 non-analyst same-type alternatives exist, substitution must
    only pick those (anl4_*/pv13_* excluded)."""
    fake_pool = {"X": ["close", "volume", "adv20", "anl4_abc", "pv13_xyz"]}
    fake_types = {f: "MATRIX" for f in fake_pool["X"]}
    monkeypatch.setattr(cg, "_load_field_pool", lambda: fake_pool)
    monkeypatch.setattr(cg, "load_field_types", lambda: fake_types)
    variants = cg._substitute_fields("ts_mean(close, 20)", n=30)
    assert variants, "expected variants"
    for v in variants:
        assert "anl4_" not in v, v
        assert "pv13_" not in v, v
        assert et.is_type_safe(v, fake_types), v


def test_c_no_timeout_prone_in_substitution():
    """R3-C coupling: no variant may touch a stall-prone field."""
    variants = cg._substitute_fields("ts_mean(close, 20)", n=40)
    if cg._HAS_TIMEOUT_GUARD:
        for v in variants:
            assert not cg.is_timeout_prone(v), v


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
