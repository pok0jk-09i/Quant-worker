"""Tests for the economic template library (P1-A block D).

Pillar ① of the WorldQuant top-playbook: ECONOMIC GROUNDING.  Templates are
formulaic alpha skeletons with explicit, literature-backed economic meaning.

Research basis (cross-validated 2026-08-02, top-tier sources only):
  * Kakushadze 101 Formulaic Alphas (arXiv:1601.00991)
  * jglazar WQ Intl Quant Championship (real IS: reversion Sharpe 1.80,
    value -ts_zscore(EV/EBITDA) Sharpe 2.00)
  * QuantGPT (ComeStart) — 3 BRAIN IS-PASS composites (Sharpe 1.60-1.77)
  * DeepWiki Alpha101 formula-pattern structures
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.economic_templates import (  # noqa: E402
    iter_template_expressions,
    build_mean_reversion_price,
    build_short_term_reversal,
    build_value_quality,
    build_low_volatility,
    build_vwap_deviation_reversal,
    build_volume_price_reversal,
)
from scripts.candidate_generator import (  # noqa: E402
    _safe_rank_wrap,
    generate_variants,
    extract_settings,
)
from core.infrastructure.timeout_field_guard import (  # noqa: E402
    timeout_prone_fields_in,
)


def test_eight_families_present():
    fams = [f for f, _, _ in iter_template_expressions()]
    assert len(fams) == 8, fams
    assert len(set(fams)) == 8, "duplicate family ids"


def test_no_timeout_prone_fields_in_base():
    for fam, expr, _hyp in iter_template_expressions():
        bad = timeout_prone_fields_in(expr)
        assert not bad, (fam, expr, sorted(bad))


def test_base_expr_rank_wrappable_and_idempotent():
    safe_ops = {"rank", "zscore", "scale", "group_rank", "group_zscore", "sign"}
    for fam, expr, _hyp in iter_template_expressions():
        wrapped = _safe_rank_wrap(expr)
        # idempotent: wrapping twice == once
        assert _safe_rank_wrap(wrapped) == wrapped, (fam, expr, wrapped)
        # either already cross-sectionally safe, or wrapped in rank(...)
        top = wrapped.split("(")[0].split()[0] if "(" in wrapped else wrapped
        top = top.lstrip("+-")  # tolerate a leading unary +/- (e.g. "-rank(...)")
        assert wrapped.startswith("rank(") or top in safe_ops, (fam, wrapped)


def test_composite_family_not_double_wrapped():
    comp = [expr for f, expr, _ in iter_template_expressions()
            if f == "debt_momentum_composite"]
    assert comp, "debt_momentum_composite family missing"
    wrapped = _safe_rank_wrap(comp[0])
    # composite already begins with '-rank(' -> treated as safe, unchanged
    assert wrapped == comp[0], wrapped
    assert wrapped.startswith("-rank("), wrapped


def test_variants_generated_rank_wrapped_and_timeout_safe():
    settings = extract_settings({})
    for fam, expr, _hyp in iter_template_expressions():
        variants = generate_variants(expr, settings, max_variants=3)
        assert variants, (fam, expr)
        for v in variants:
            e = v["expression"]
            assert e.startswith("rank(") or _safe_rank_wrap(e) == e, (fam, e)
            assert not timeout_prone_fields_in(e), (fam, e)


def test_family_carries_hypothesis():
    for fam, _expr, hyp in iter_template_expressions():
        assert hyp and isinstance(hyp, str), (fam, hyp)


def test_template_expressions_balanced_parens():
    for _fam, expr, _hyp in iter_template_expressions():
        assert expr.count("(") == expr.count(")"), expr


def test_generate_variants_substitute_false_keeps_base_pure():
    # Economic templates must keep their researched economic meaning; field
    # substitution (which could swap e.g. high->split) is disabled for them.
    settings = extract_settings({})
    base = _safe_rank_wrap(build_mean_reversion_price())
    vs = generate_variants(build_mean_reversion_price(), settings,
                           max_variants=3, substitute=False)
    assert vs
    for v in vs:
        assert v["expression"] == base, (v["expression"], base)


@pytest.mark.parametrize("lb", [3, 5, 10, 20, 33, 63, 120, 250])
def test_lookback_fuzz_balanced_and_safe(lb):
    builders = [
        build_short_term_reversal,
        build_value_quality,
        build_low_volatility,
        build_vwap_deviation_reversal,
        build_volume_price_reversal,
    ]
    for fn in builders:
        s = fn(lookback=lb)
        assert s.count("(") == s.count(")"), s
        assert not timeout_prone_fields_in(s), s
