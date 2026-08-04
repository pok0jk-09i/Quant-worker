# STORY: S-p1a-seedpool (Gen-4 门③ contract test for P1A/SEEDPOOL)
"""Consumer-driven contract test: timeout_field_guard -> candidate_generator / candidate_submitter.

The guard is consumed by two roles with two distinct, load-bearing behaviors:

* ``scripts/candidate_generator.py`` (R3-C) imports ``is_timeout_prone`` AND the
  frozen ``TIMEOUT_PRONE_FIELDS``.  It (a) never substitutes a stall-prone field
  IN during variant generation, and (b) DROPS any candidate whose expression
  ``is_timeout_prone(expr)`` is True — so a sim that would hang at ~35% is never
  spawned.
* ``scripts/candidate_submitter.py`` (R3-A) imports ``is_timeout_prone`` AND
  ``timeout_prone_fields_in``.  It SKIPs a candidate (status
  ``SKIPPED_TIMEOUT_RISK``) when ``timeout_prone_fields_in(expr)`` is non-empty,
  recovering the full 600s poll window.

This test is the CONTRACT: it pins the exact interface + verdicts those two
consumers encode, and it is the single place that would break if a future guard
change silently altered generation/submit behavior.  Run by gate_contract (门③).

Run: python -m pytest tests/test_timeout_guard_contract.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure import timeout_field_guard as g  # noqa: E402


def _load_contract() -> dict:
    path = ROOT / "team" / "contracts" / "contracts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for c in data.get("contracts", []):
        if c.get("provider", "").startswith("core/infrastructure/timeout_field_guard"):
            return c
    raise AssertionError("timeout_field_guard contract not declared in contracts.json")


# The consumer decision models — these mirror EXACTLY what the two consumers
# do with the guard's API, so the contract ties to real behavior (not just the
# provider's internals).
def generator_keeps(candidate: dict) -> bool:
    """candidate_generator R3-C: drop iff is_timeout_prone(expr)."""
    return not g.is_timeout_prone(candidate.get("expression", ""))


def submitter_skips(candidate: dict) -> bool:
    """candidate_submitter R3-A: skip iff timeout_prone_fields_in(expr) non-empty."""
    return bool(g.timeout_prone_fields_in(candidate.get("expression", "")))


def test_guard_contract_api_present():
    """门③: the provider exposes the exact API the consumers import."""
    contract = _load_contract()
    required = contract.get("required_api", [])
    assert required, "contract must declare required_api"
    assert callable(g.is_timeout_prone)
    assert callable(g.timeout_prone_fields_in)
    assert isinstance(g.TIMEOUT_PRONE_FIELDS, frozenset)


def test_guard_contract_stall_fields_blocked():
    """Provider verdict for a known 100%-stall field matches BOTH consumers."""
    contract = _load_contract()
    stall = contract.get("sample_stall_field") or "anl4_fs_guidances_advanced_af_nd_epsr_maxguidance"
    assert stall in g.TIMEOUT_PRONE_FIELDS, "sample stall field must be in frozen core"

    expr = f"-ts_zscore({stall})"
    cand = {"expression": expr}
    # Both consumers agree: a stall field is blocked.
    assert g.is_timeout_prone(expr) is True
    assert g.timeout_prone_fields_in(expr) == [stall]
    assert generator_keeps(cand) is False, "generator must DROP stall-prone candidate"
    assert submitter_skips(cand) is True, "submitter must SKIP stall-prone candidate"


def test_guard_contract_core_fields_never_blocked():
    """Hard invariant: universally-covered market fields must NEVER break generation/submit.

    This is the regression contract for the ``open`` false-positive: a core price
    field must be neither flagged by the guard nor dropped/skipped by either
    consumer, even if the live results file shows a small-sample 100%-stall.
    """
    contract = _load_contract()
    core = contract.get("core_never_blocked", list(g.NEVER_BLOCK_CORE))
    assert core, "contract must declare core_never_blocked"

    for f in core:
        expr = f"ts_mean({f}, 20)"
        cand = {"expression": expr}
        assert g.is_timeout_prone(expr) is False, f"core field {f} must not be flagged"
        assert g.timeout_prone_fields_in(expr) == [], f"core field {f} must not be listed"
        assert generator_keeps(cand) is True, f"generator must KEEP core-field candidate {f}"
        assert submitter_skips(cand) is False, f"submitter must NOT skip core-field candidate {f}"


def test_guard_contract_frozen_excludes_core():
    """The frozen prevention core must never contain a core market field, so the
    generator's field-substitution filter (which uses TIMEOUT_PRONE_FIELDS
    directly, not the effective set) can never strip a valid field."""
    contract = _load_contract()
    core = set(contract.get("core_never_blocked", g.NEVER_BLOCK_CORE))
    leaked = sorted(core & g.TIMEOUT_PRONE_FIELDS)
    assert not leaked, f"frozen core leaks core market fields: {leaked}"


def test_guard_contract_adversarial_core_wins_over_data():
    """Drift-proof + whitelist: a synthetic results file claiming ``open``/
    ``close`` are 100%-stall must NOT make the guard block them — the whitelist
    wins over the data-derived rebuild for BOTH consumer verdicts."""
    synthetic = [
        {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_mean(open, 20)"}},
        {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_mean(open, 20)"}},
        {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_zscore(close)"}},
        {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_zscore(close)"}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(synthetic, fh)
        tmp = fh.name
    try:
        eff = g.effective_timeout_blocklist(tmp)
        assert "open" not in eff and "close" not in eff
        # Both consumers keep these valid candidates despite the fake signal.
        assert generator_keeps({"expression": "ts_mean(open, 20)"}) is True
        assert submitter_skips({"expression": "rank(-ts_decay_linear(adv20 / open, 10))"}) is False
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_guard_contract_deterministic_and_monotonic():
    """The guard is deterministic given (frozen core + results file), and adding
    a NEW observed stall field only GROWS the blocked set — it can never remove
    a core field's safety (the property that makes the guard safe to evolve)."""
    contract = _load_contract()
    new_stall = contract.get("sample_new_stall_field") or "research_development_expense"

    synthetic = [
        {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": f"-ts_zscore({new_stall})"}},
        {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": f"-ts_zscore({new_stall})"}},
    ]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(synthetic, fh)
        tmp = fh.name
    try:
        eff1 = g.effective_timeout_blocklist(tmp)
        eff2 = g.effective_timeout_blocklist(tmp)
        assert eff1 == eff2, "guard must be deterministic for the same inputs"
        # Adding the new stall field grows the effective set (monotonic).
        assert new_stall in eff1, "new observed stall field must be blocked"
        assert g.NEVER_BLOCK_CORE.isdisjoint(eff1), "core safety preserved under data drift"
    finally:
        Path(tmp).unlink(missing_ok=True)
