"""Nightly Gate entry (Gen-4 CI) — heavy / slow coverage excluded from the fast merge gate.

WHY A SEPARATE GATE
-------------------
The fast merge gate (team/ci/run_merge_gate.py, 门①②③④) deliberately EXCLUDES
the real-data integration test ``tests/test_seed_pool.py::test_build_real_parent_pool_real_db``
(which loads the 14 MB ``alpha_db.json`` and runs the real parent-pool build) and
uses a faster mutation subset.  That keeps pre-merge checks in seconds.  But the
real-data path is exactly the kind of coverage you must NOT silently drop — so it
lives here, in the NIGHTLY gate, run on a schedule (cron / scheduled CI), not on
every PR.

This gate runs the FULL suite WITH the real_db integration test + ruff, and
writes ``team/specs/nightly_gate_<STORY>.json``.  It is the big-tech idiom:
fast gate on merge, full gate nightly.

Run:
    python team/ci/run_nightly_gate.py P1A SEEDPOOL
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SPEC_DIR = ROOT / "team" / "specs"
PY = "E:/Python311/python.exe"

# Suites covered by the nightly gate (full — NO 'not real_db' exclusion).
TEST_TARGETS = ["tests/", "core/infrastructure/tests/"]
RUFF_TARGETS = ["core/infrastructure/", "team/", "tests/", "core/infrastructure/tests/"]


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


def _parse_pytest(out: str) -> dict:
    m = re.search(r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) skipped)?", out)
    passed = int(m.group(1)) if m else 0
    failed = int(m.group(2)) or 0 if m and m.group(2) else 0
    skipped = int(m.group(3)) or 0 if m and m.group(3) else 0
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "summary": out.strip().splitlines()[-1] if out.strip() else ""}


def run_nightly(epic: str = "P1A", story: str = "SEEDPOOL") -> int:
    print(f"[nightly] begin nightly gate for {epic}/{story}")

    # ── ruff ──
    rc_lint, lint_out = _run([PY, "-m", "ruff", "check", *RUFF_TARGETS])
    lint_ok = rc_lint == 0

    # ── FULL pytest (real_db INCLUDED) ──
    rc_test, test_out = _run(
        [PY, "-m", "pytest", *TEST_TARGETS, "-q"]
    )
    test_stats = _parse_pytest(test_out)
    test_ok = rc_test == 0 and test_stats["failed"] == 0

    ok = lint_ok and test_ok
    verdict = {
        "gate": "nightly",
        "epic": epic,
        "story": story,
        "decision": "PASS" if ok else "FAIL",
        "lint": {"ok": lint_ok, "output": lint_out.strip().splitlines()[-3:]},
        "tests": {**test_stats, "real_db_included": True},
        "note": "real-data integration path (alpha_db.json) gated here, not in the fast merge gate",
        "generated_by": "team/ci/run_nightly_gate.py",
    }
    out_path = SPEC_DIR / f"nightly_gate_{story}.json"
    out_path.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[nightly] decision = {verdict['decision']} -> {out_path}")
    if not lint_ok:
        print("[nightly][FAIL] ruff:\n" + lint_out)
    if not test_ok:
        print("[nightly][FAIL] pytest:\n" + test_out)
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    epic = args[0] if len(args) >= 1 else "P1A"
    story = args[1] if len(args) >= 2 else "SEEDPOOL"
    sys.exit(run_nightly(epic, story))
