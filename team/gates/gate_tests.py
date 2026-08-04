"""门② 测试通过 (Test Gate).

Runs the FULL three-layer verification stack (STDD §8):
  * **Lint**   — ruff on ``scripts/`` and ``core/``
  * **Tests**  — pytest on BOTH test dirs (``tests/`` + ``core/infrastructure/tests/``),
                which include unit / integration / property-based (hypothesis) suites.

Exit 0 = ruff clean AND pytest green; 1 = either failed.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
INFRA = ROOT / "core" / "infrastructure"
TESTS = ROOT / "tests"
INFRA_TESTS = INFRA / "tests"

PY = "E:/Python311/python.exe"
RUFF = "E:/Python311/Scripts/ruff.exe"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def gate_lint() -> tuple[bool, str]:
    r = _run([RUFF, "check", str(SCRIPTS), str(INFRA)])
    ok = r.returncode == 0
    return ok, (r.stdout.strip()[-1500:] if not ok else "ruff clean")


def gate_pytest() -> tuple[bool, int]:
    r = _run([PY, "-m", "pytest", str(TESTS), str(INFRA_TESTS), "-q"])
    passed = 0
    for line in r.stdout.splitlines():
        if "passed" in line:
            try:
                passed = int(line.split()[0])
            except ValueError:
                pass
    ok = r.returncode == 0
    return ok, passed


def run(epic: str, story: str, trace_id: str | None = None) -> tuple[bool, dict]:
    lint_ok, lint_msg = gate_lint()
    test_ok, passed = gate_pytest()
    ok = lint_ok and test_ok
    return ok, {"lint": lint_ok, "lint_msg": lint_msg,
                "tests_passed": passed, "ok": ok,
                "detail": "ruff + pytest green" if ok else "test/lint failure"}
