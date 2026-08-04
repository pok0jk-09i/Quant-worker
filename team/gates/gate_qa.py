"""门④ 独立评估 (Independent Evaluator Gate).

The hard quality bar (STDD Door 4).  Reuses ``team/qa_gate.py``'s mutation
parser but points mutation at the configured target set (default
``team/ci/cosmic_seed_pool.toml``).  The writer of the code under test NEVER
runs this gate — it is the QA role's independent verdict.

  * **Lint**     — ruff clean
  * **Tests**    — pytest both dirs green
  * **Mutation** — cosmic-ray score >= 0.70, no incompetent / timeout

Exit 0 = all three green; 1 = any failed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "core" / "infrastructure"
TESTS = ROOT / "tests"
INFRA_TESTS = INFRA / "tests"

PY = "E:/Python311/python.exe"
RUFF = "E:/Python311/Scripts/cosmic-ray.exe" if False else "E:/Python311/Scripts/ruff.exe"
COSMIC = "E:/Python311/Scripts/cosmic-ray.exe"
MUTATION_THRESHOLD = 0.70
DEFAULT_CONFIG = ROOT / "team" / "ci" / "cosmic_seed_pool.toml"
_SESS = ROOT / "cr-session-seedpool.json"
_DUMP = ROOT / "cr-dump-seedpool.jsonl"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def gate_lint() -> tuple[bool, str]:
    r = _run([RUFF, "check", str(ROOT / "scripts"), str(INFRA)])
    ok = r.returncode == 0
    return ok, (r.stdout.strip()[-1500:] if not ok else "ruff clean")


def gate_tests() -> tuple[bool, int]:
    r = _run([PY, "-m", "pytest", str(TESTS), str(INFRA_TESTS), "-q"])
    passed = 0
    for line in r.stdout.splitlines():
        if "passed" in line:
            try:
                passed = int(line.split()[0])
            except ValueError:
                pass
    return r.returncode == 0, passed


# Hard wall-clock for the mutation step.  cosmic-ray's `local` distributor is
# perfectly fine on a native Windows console (PowerShell/cmd) — empirically it
# runs 11 mutants in ~30s.  The HANG we hit earlier was caused by launching it
# under Git-Bash/MSYS, where the worker subprocess spawn never returns.  So the
# budget here guards against a genuine stall, not normal work.  30 min cap is
# ample for the seed_pool target set (~50-120 mutants).
MUTATION_TIMEOUT_SECONDS = 1800


def _run_mutation(config: Path) -> Path:
    # NOTE: we rely on `init --force` rather than unlinking the stale session
    # first.  In some sandboxed environments `Path.unlink` is intercepted by a
    # safe-delete shim that fails to actually remove the file, leaving a stale
    # session behind and making a plain `init` refuse ("already contains
    # results").  `--force` makes the gate idempotent and re-runnable.
    _DUMP.unlink(missing_ok=True)
    init = _run([COSMIC, "init", "--force", str(config), str(_SESS)])
    if init.returncode != 0:
        raise RuntimeError(
            f"cosmic-ray init failed (rc={init.returncode}): "
            f"{init.stderr.strip()[:500]}"
        )
    try:
        subprocess.run(
            [COSMIC, "exec", str(config), str(_SESS)],
            cwd=ROOT, capture_output=True, text=True,
            timeout=MUTATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"cosmic-ray exec exceeded the {MUTATION_TIMEOUT_SECONDS}s wall-clock "
            "budget and was killed. If you launched this from Git-Bash/MSYS the "
            "local distributor's worker spawn HANGS — re-run the four-gate suite "
            "from a NATIVE Windows console (PowerShell or cmd.exe), e.g. "
            "`powershell -NoProfile -ExecutionPolicy Bypass -File ...`. "
            "cosmic-ray is verified working there. See team/RUNBOOK.md §7."
        )
    with open(_DUMP, "w") as fh:
        subprocess.run([COSMIC, "dump", str(_SESS)],
                       cwd=ROOT, stdout=fh, stderr=subprocess.PIPE,
                       text=True, check=True)
    return _DUMP


def gate_mutation(config: str | None = None) -> tuple[bool, dict]:
    cfg = Path(config) if config else DEFAULT_CONFIG
    if not cfg.exists():
        return False, {"error": f"mutation config missing: {cfg}"}
    from team import qa_gate as _qa   # reuse the verified parser
    try:
        dump = _run_mutation(cfg)
    except RuntimeError as exc:
        # Environment cannot run mutation (tool hangs / unavailable).  Fail the
        # leg HONESTLY with a clear, actionable reason instead of hanging or
        # silently passing.  The gate system is correct; only the mutation
        # engine is unavailable on this workstation.
        return False, {
            "available": False,
            "error": str(exc),
            "hint": "If this was launched from Git-Bash/MSYS, re-run from a native "
                    "Windows console (PowerShell/cmd) — cosmic-ray's local "
                    "distributor hangs under MSYS but works natively. The GitHub "
                    "Actions workflow .github/workflows/merge_gate.yml runs on "
                    "Linux and also invokes this exact gate.",
            "ok": False,
        }
    stats = _qa._parse_dump(dump)
    ok = (stats["standard_score"] >= MUTATION_THRESHOLD
          and stats["incompetent"] == 0 and stats["timeout"] == 0)
    return ok, {**stats, "threshold": MUTATION_THRESHOLD, "ok": ok,
                "available": True}


def run(epic: str, story: str, trace_id: str | None = None,
        mutation_config: str | None = None) -> tuple[bool, dict]:
    lint_ok, lint_msg = gate_lint()
    test_ok, passed = gate_tests()
    mut_ok, mut_stats = gate_mutation(mutation_config)
    ok = lint_ok and test_ok and mut_ok
    return ok, {"lint": lint_ok, "lint_msg": lint_msg,
                "tests_passed": passed, "mutation": mut_stats, "ok": ok,
                "detail": "independent evaluator green" if ok else "QA gate failure"}
