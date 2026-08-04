# STORY: S-p1a-seedpool (Gen-4 门③ contract test for P1A/SEEDPOOL)
"""Consumer-driven contract test: seed_pool -> candidate_generator.

Verifies the provider (build_real_parent_pool / to_candidate_dict) emits output
that satisfies the consumer's expected schema declared in
team/contracts/contracts.json.  Run by gate_contract (门③).

Run: python -m pytest tests/test_seed_pool_contract.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.infrastructure.seed_pool import build_real_parent_pool, to_candidate_dict  # noqa: E402


def _load_contract():
    path = ROOT / "team" / "contracts" / "contracts.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for c in data.get("contracts", []):
        if c.get("provider", "").startswith("core/infrastructure/seed_pool"):
            return c
    raise AssertionError("seed_pool contract not declared")


def _db():
    return {"alphas": {
        "0": {"status": "UNSUBMITTED", "fitness": 1.4, "sharpe": 1.6,
              "turnover": 0.2, "expression": "-ts_mean(returns, 33)",
              "settings": {"region": "USA", "universe": "TOP3000", "decay": 4,
                           "neutralization": "SUBINDUSTRY", "truncation": 0.01}},
        "1": {"status": "ACTIVE", "fitness": 1.9, "sharpe": 2.0,
              "turnover": 0.1, "expression": "rank(close)",
              "settings": {"region": "USA", "universe": "TOP3000"}},
    }}


def test_seed_pool_contract_schema():
    contract = _load_contract()
    required = set(contract["required_keys"])
    settings_required = set(contract["settings_required_keys"])

    res = build_real_parent_pool(_db(), fitness_min=1.0)
    # build at least one candidate dict from each tier present
    samples = [to_candidate_dict(r) for r in (res["pool"] or res["tier0"])]
    assert samples, "contract: no provider output produced"

    for item in samples:
        # required top-level keys
        missing = required - set(item.keys())
        assert not missing, f"contract violation: missing {missing}"
        assert isinstance(item["expression"], str) and item["expression"]
        # required nested settings keys
        s_missing = settings_required - set(item["settings"].keys())
        assert not s_missing, f"contract violation: settings missing {s_missing}"
        # types
        assert isinstance(item["settings"], dict)
        assert item["settings"]["region"] in ("USA", "TOP3000", "IND", "TOP2000", "GLB")
        assert isinstance(item["settings"]["decay"], (int, float))
        assert item["settings"]["truncation"] >= 0
