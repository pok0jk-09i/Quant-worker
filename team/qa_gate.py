"""STDD Door 4 — Independent Evaluator gate.

This script is the INDEPENDENT EVALUATOR. It is run as a fresh process with
NO knowledge of how the code under test was written. It only observes
behaviour through three verifiable signals:

  1. Lint      (ruff)            -> no style/import errors
  2. Tests     (pytest + PBT)    -> all unit / property-based tests green
  3. Mutation  (cosmic-ray)      -> mutation score >= THRESHOLD (default 0.70)

The mutation gate is the hard quality bar. Coverage % is NOT used: we measure
how many injected faults the test-suite actually catches (mutation score).

Exit code 0  => all four STDD doors verified, safe to merge
Exit code 1  => one or more gates failed; do NOT merge

Run:
    python team/qa_gate.py                 # fresh init+exec+dump
    python team/qa_gate.py --reuse-dump cr-dump.jsonl   # use existing dump
    python team/qa_gate.py --mutation-threshold 0.70
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ---- Paths (project-root relative) -----------------------------------------
ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "core" / "infrastructure"
TESTS = INFRA / "tests"
CONFIG = ROOT / "cosmic-ray.toml"
SESSION = ROOT / "cr-session.json"
DUMP = ROOT / "cr-dump.jsonl"

# Pin to the project's fixed interpreter (E:/Python311/python.exe) — this is the
# PINNED_PYTHON the whole project runs on, and where pytest/hypothesis/ruff/
# cosmic-ray are installed. Do NOT resolve via shutil.which(), which can pick up
# a different managed interpreter on PATH and silently run tests without deps.
PY = "E:/Python311/python.exe"
RUFF = "E:/Python311/Scripts/ruff.exe"
COSMIC = "E:/Python311/Scripts/cosmic-ray.exe"

MUTATION_THRESHOLD = 0.70
TIMEOUT_PER_MUTANT = 300


def _run(cmd, **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def gate_lint() -> tuple[bool, str]:
    r = _run([RUFF, "check", str(INFRA)])
    ok = r.returncode == 0
    return ok, (r.stdout.strip() if not ok else "ruff clean")


def gate_tests() -> tuple[bool, int, str]:
    r = _run([PY, "-m", "pytest", str(TESTS), "-q"])
    # parse "N passed" from output
    passed = 0
    for line in r.stdout.splitlines():
        if "passed" in line:
            try:
                passed = int(line.split()[0])
            except ValueError:
                pass
    ok = r.returncode == 0
    return ok, passed, (r.stdout.strip()[-2000:] if not ok else f"{passed} passed")


def _run_mutation() -> Path:
    # fresh init + exec + dump
    SESSION.unlink(missing_ok=True)
    DUMP.unlink(missing_ok=True)
    _run([COSMIC, "init", str(CONFIG), str(SESSION)])
    _run([COSMIC, "exec", str(CONFIG), str(SESSION)])
    # cosmic-ray `dump` writes NDJSON to stdout; redirect it to the dump file.
    with open(DUMP, "w") as fh:
        subprocess.run(
            [COSMIC, "dump", str(SESSION)],
            cwd=ROOT, stdout=fh, stderr=subprocess.PIPE, text=True, check=True,
        )
    return DUMP


def _parse_dump(path: Path) -> dict:
    """Parse cosmic-ray NDJSON dump.

    Each line is a 2-element list ``[WorkItem, WorkResult]`` (or a list whose
    second element may be null when a work item has no result). The mutation
    outcome lives in ``WorkResult["test_outcome"]``.
    """
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # normalise to (workitem, workresult)
            if isinstance(rec, list):
                wi = rec[0] if len(rec) > 0 else None
                wr = rec[1] if len(rec) > 1 else None
            else:
                wi, wr = rec, None
            records.append((wi, wr))

    counts: dict[str, int] = {}
    for wi, wr in records:
        if wr is None:
            oc = "no_result"
        else:
            oc = wr.get("test_outcome", "unknown")
        counts[oc] = counts.get(oc, 0) + 1

    killed = counts.get("killed", 0)
    survived = counts.get("survived", 0)
    incompetent = counts.get("incompetent", 0)
    timeout = counts.get("timeout", 0)
    no_result = counts.get("no_result", 0)
    total = killed + survived + incompetent + timeout
    # standard mutation score excludes incompetent/timeout from denominator
    std_denom = killed + survived
    standard_score = (killed / std_denom) if std_denom else 0.0
    # strict score: anything not killed is a failure to certify
    strict_score = (killed / total) if total else 0.0
    return {
        "records": len(records),
        "killed": killed,
        "survived": survived,
        "incompetent": incompetent,
        "timeout": timeout,
        "no_result": no_result,
        "total": total,
        "standard_score": standard_score,
        "strict_score": strict_score,
        "outcome_key": "test_outcome",
        "raw_counts": counts,
    }


def gate_mutation(reuse_dump: str | None) -> tuple[bool, dict]:
    if reuse_dump:
        dump_path = Path(reuse_dump)
        if not dump_path.is_absolute():
            dump_path = ROOT / dump_path
    else:
        dump_path = _run_mutation()
    stats = _parse_dump(dump_path)
    score = stats["standard_score"]
    ok = (score >= MUTATION_THRESHOLD and
          stats["incompetent"] == 0 and
          stats["timeout"] == 0)
    return ok, stats


def main() -> int:
    global MUTATION_THRESHOLD
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-dump", default=None,
                    help="Path to an existing cosmic-ray dump (skip init/exec)")
    ap.add_argument("--mutation-threshold", type=float, default=0.70)
    args = ap.parse_args()
    MUTATION_THRESHOLD = args.mutation_threshold

    print("=" * 70)
    print("STDD DOOR 4 — INDEPENDENT EVALUATOR")
    print("=" * 70)

    print("\n[1/3] Lint gate (ruff) ...")
    lint_ok, lint_msg = gate_lint()
    print(f"    {'PASS' if lint_ok else 'FAIL'} :: {lint_msg}")

    print("\n[2/3] Test gate (pytest + PBT) ...")
    test_ok, n_passed, test_msg = gate_tests()
    print(f"    {'PASS' if test_ok else 'FAIL'} :: {n_passed} tests passed"
          if test_ok else f"    FAIL :: {test_msg}")

    print("\n[3/3] Mutation gate (cosmic-ray) ...")
    mut_ok, stats = gate_mutation(args.reuse_dump)
    print(f"    outcome_key={stats['outcome_key']} records={stats['records']}")
    print(f"    killed={stats['killed']} survived={stats['survived']} "
          f"incompetent={stats['incompetent']} timeout={stats['timeout']}")
    print(f"    standard mutation score = {stats['standard_score']:.4f}")
    print(f"    strict   mutation score = {stats['strict_score']:.4f}")
    print(f"    threshold = {MUTATION_THRESHOLD}")
    print(f"    {'PASS' if mut_ok else 'FAIL'}")

    all_ok = lint_ok and test_ok and mut_ok
    print("\n" + "=" * 70)
    print(f"OVERALL: {'ALL DOORS PASS — SAFE TO MERGE' if all_ok else 'GATE FAILED — DO NOT MERGE'}")
    print("=" * 70)

    report = {
        "lint": lint_ok,
        "tests": {"ok": test_ok, "passed": n_passed},
        "mutation": {**stats, "threshold": MUTATION_THRESHOLD, "ok": mut_ok},
        "merge_allowed": all_ok,
    }
    (ROOT / "qa_gate_report.json").write_text(json.dumps(report, indent=2))
    print("Report written -> qa_gate_report.json")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
