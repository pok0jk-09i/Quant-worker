"""门③ 契约通过 (Consumer-Driven Contract Gate).

Runs the consumer-driven contract tests declared in
``team/contracts/contracts.json``.  Each contract names a provider/consumer pair
and a pytest file asserting the provider's output satisfies the consumer's
expected schema/behavior.  For our monorepo this is the lightweight stand-in for
pact-python (cross-process) — same discipline, no extra infra.

Exit 0 = all contract tests green; 1 = any failed or a declared contract test
is missing.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "team" / "contracts" / "contracts.json"
TESTS = ROOT / "tests"

PY = "E:/Python311/python.exe"


def run(epic: str, story: str, trace_id: str | None = None) -> tuple[bool, dict]:
    if not CONTRACTS.exists():
        # No contracts declared yet — diagnostic pass (do not hard-block).
        return True, {"contracts": 0, "detail": "no contracts declared (diagnostic)"}
    data = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    entries = data.get("contracts", [])
    failed: list[str] = []
    for c in entries:
        name = c.get("name", "?")
        test_file = c.get("test")
        if not test_file or not (ROOT / test_file).exists():
            failed.append(f"{name}: contract test missing ({test_file})")
            continue
        r = subprocess.run([PY, "-m", "pytest", str(ROOT / test_file), "-q"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            failed.append(f"{name}: contract test FAILED")
    ok = len(failed) == 0
    return ok, {"contracts": len(entries), "failed": failed,
                "detail": "all contracts satisfied" if ok else f"{len(failed)} contract(s) failed"}
