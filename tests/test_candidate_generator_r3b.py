"""Tests for R3-B: type-preserving field substitution.

`_substitute_fields` must never swap a field for one of a DIFFERENT BRAIN
type -- that is what produced the 44 type-incompatible simulation errors
(GROUP/SYMBOL/EVENT fed into ts_*/arith).  These tests prove that variants
generated from a numeric (MATRIX) field stay type-safe: no non-numeric field
is ever introduced into a ts_*/arithmetic context.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import expression_types as et  # noqa: E402
from scripts.candidate_generator import _substitute_fields  # noqa: E402


@pytest.fixture(scope="module")
def field_types():
    return et.load_field_types()


def test_substitution_keeps_type_safe(field_types):
    # close is MATRIX.  Every variant must remain type-safe (no GROUP/SYMBOL/
    # EVENT introduced into ts_mean's arguments).
    variants = _substitute_fields("ts_mean(close, 20)", n=25)
    assert variants, "expected some variants to be generated"
    for v in variants:
        viol = et.validate_expression(v, field_types)
        assert viol == [], f"variant introduced type violation: {v} -> {viol}"


def test_substitution_of_group_field_stays_group(field_types):
    # industry is GROUP.  Substituting within its category with same-type
    # filter keeps it GROUP (which is fine in group_rank's group argument).
    variants = _substitute_fields("group_rank(close, industry)", n=25)
    for v in variants:
        # No field inside the expression may become non-numeric-in-ts_*.
        viol = et.validate_expression(v, field_types)
        assert viol == [], f"variant introduced type violation: {v} -> {viol}"
