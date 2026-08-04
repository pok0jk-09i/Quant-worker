"""Runtime environment contract enforcement.

WHY THIS EXISTS
---------------
The Quant worker stack has died *repeatedly* because it was launched with the
wrong Python interpreter (a managed 3.13 build without ``requests`` /
``numpy``) or with missing dependencies. A supervised child that imports
at startup and then crashes is invisible to naive health checks until it
has already taken the entire supervision tree down with it.

This module makes the contract *explicit and fail-fast*. Every entry
point (start.py, project_runtime.py, each submitter) calls
``assert_runtime_contract()`` as its *first* statement. If the contract
is violated it raises ``SystemExit(78)`` (EX_CONFIG) with an actionable
message, so the supervisor sees a clean, diagnosable failure instead of a
mysterious import-time traceback buried in a child's stderr.

DESIGN NOTES
------------
* ``required_executable`` is the single most important guard: it compares
  the *realpath* of the running interpreter against the one that is known
  to have the correct dependencies installed. No more "inherited the
  wrong python from the launcher".
* Missing packages are reported with the exact ``pip install`` command.
* Exit code 78 (EX_CONFIG) is deliberately distinct from a normal crash
  (exit 1) so the supervisor can classify the restart correctly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib import import_module
from typing import Iterable, Optional

# UNIX EX_CONFIG — "configuration error". Chosen so a contract violation is
# distinguishable from a runtime crash in logs and in restart classifiers.
EX_CONFIG = 78


class RuntimeContractError(RuntimeError):
    """Raised (non-fatal path) when the runtime contract is violated."""

    def __init__(self, message: str, *, code: int = EX_CONFIG) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RuntimeContract:
    """The environment a Quant worker process is allowed to run under."""

    min_python: tuple[int, int] = (3, 11)
    required_packages: tuple[str, ...] = ("requests", "numpy")
    # When set, the *currently running* interpreter must match this path
    # (by realpath) or we refuse to run. This is the guard against the
    # "launched with the wrong python" class of outages.
    required_executable: Optional[str] = None


def _running_python_ok(min_python: tuple[int, int]) -> tuple[bool, str]:
    cur = sys.version_info[:2]
    return (cur >= min_python, f"{cur[0]}.{cur[1]}")


def _executable_ok(required: Optional[str]) -> tuple[bool, str]:
    if not required:
        return True, sys.executable
    try:
        want = os.path.realpath(required)
        have = os.path.realpath(sys.executable)
    except Exception:
        return False, sys.executable
    return (want == have), have


def _packages_ok(packages: Iterable[str]) -> tuple[list[str], list[str]]:
    ok: list[str] = []
    missing: list[str] = []
    for pkg in packages:
        try:
            mod = import_module(pkg)
            ok.append(f"{pkg}=={getattr(mod, '__version__', '?')}")
        except Exception:
            missing.append(pkg)
    return ok, missing


def check_contract(contract: Optional[RuntimeContract] = None) -> list[str]:
    """Return a list of human-readable violations (empty list == OK)."""
    c = contract or RuntimeContract()
    violations: list[str] = []

    py_ok, py_ver = _running_python_ok(c.min_python)
    if not py_ok:
        violations.append(
            f"Python {py_ver} is older than required "
            f"{c.min_python[0]}.{c.min_python[1]}"
        )

    ex_ok, ex_have = _executable_ok(c.required_executable)
    if not ex_ok:
        violations.append(
            f"Running interpreter {ex_have!r} != required "
            f"{c.required_executable!r}"
        )

    _ok, missing = _packages_ok(c.required_packages)
    if missing:
        violations.append(
            "Missing required packages: "
            + ", ".join(missing)
            + "  ->  fix with: pip install "
            + " ".join(missing)
        )
    return violations


def assert_runtime_contract(
    contract: Optional[RuntimeContract] = None,
    *,
    exit_on_violation: bool = True,
) -> list[str]:
    """Assert the contract. Returns violations if OK; otherwise exits/raises.

    Parameters
    ----------
    contract:
        Override the default contract (e.g. to pin ``required_executable``
        to the system Python 3.11 path).
    exit_on_violation:
        If True (default), print a diagnostic to stderr and call
        ``sys.exit(EX_CONFIG)``. If False, raise ``RuntimeContractError``
        instead so callers can decide what to do.
    """
    violations = check_contract(contract)
    if not violations:
        return violations

    message = (
        "RUNTIME CONTRACT VIOLATED — refusing to start.\n  - "
        + "\n  - ".join(violations)
        + "\nFix the environment, then relaunch. Do NOT let a supervisor "
        "silently inherit a broken interpreter."
    )
    if exit_on_violation:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
        raise SystemExit(EX_CONFIG)
    raise RuntimeContractError(message)
