"""Tests for E-block feedback bias wired into generate_variants (test-first).

The bias nudges the parameter SWEEP CENTER toward empirically preferred values
(from real BRAIN IS).  Because the systematic sweep enumerates every option
EXCEPT the current center, the deterministic observable is: the *specific*
sweep (decay / neut / trunc) no longer contains the biased center value and
now contains the former center.  We assert only on that sweep's variants
(variant_type prefixed with "base:<param>="), which is Phase-1-deterministic.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.candidate_generator import generate_variants  # noqa: E402


def _sweep(variants, param):
    return [v for v in variants
            if v["variant_type"].startswith(f"base:{param}=")]


def _decays(variants):
    return {v["settings"]["decay"] for v in _sweep(variants, "decay")}


def _neuts(variants):
    return {v["settings"]["neutralization"] for v in _sweep(variants, "neut")}


def test_no_feedback_keeps_default_base():
    vs = generate_variants("rank(close)", {"decay": 4, "truncation": 0.01,
                                            "neutralization": "SUBINDUSTRY"},
                           max_variants=80, substitute=False)
    # default base: decay 4 / neut SUBINDUSTRY are the sweep centers -> skipped
    assert 4 not in _decays(vs)
    assert "SUBINDUSTRY" not in _neuts(vs)
    # alternatives present in their sweeps
    assert 20 in _decays(vs)
    assert "NONE" in _neuts(vs)


def test_feedback_bias_shifts_sweep_center():
    fbias = {"available": True, "preferred_decay": 20,
             "preferred_truncation": 0.12, "preferred_neutralization": "NONE"}
    vs = generate_variants("rank(close)", {"decay": 4, "truncation": 0.01,
                                            "neutralization": "SUBINDUSTRY"},
                           max_variants=80, substitute=False, feedback_bias=fbias)
    # bias moved center -> decay 20 / neut NONE skipped; former centers now swept
    assert 20 not in _decays(vs)
    assert "NONE" not in _neuts(vs)
    assert 4 in _decays(vs)
    assert "SUBINDUSTRY" in _neuts(vs)


def test_feedback_bias_partial_only_nudges_provided():
    fbias = {"available": True, "preferred_decay": 16}  # only decay
    vs = generate_variants("rank(close)", {"decay": 4, "truncation": 0.01,
                                            "neutralization": "SUBINDUSTRY"},
                           max_variants=80, substitute=False, feedback_bias=fbias)
    # decay center moved to 16 (skipped); 4 now swept
    assert 16 not in _decays(vs)
    assert 4 in _decays(vs)
    # neutralization unchanged (still SUBINDUSTRY center -> skipped)
    assert "SUBINDUSTRY" not in _neuts(vs)
