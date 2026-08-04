"""Portable Merge Gate entry (Gen-4 CI).

Runs the four Merge Gates (门①-门④) for the SEEDPOOL story through the Tech
Lead orchestrator and exits with the gate verdict.  Used by GitHub Actions and
local pre-merge checks.  On Windows the pinned interpreter (E:/Python311) is
used by the gate subprocesses automatically (see team/qa_gate.py / gate_*.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from team.runtime.orchestrator import run_merge  # noqa: E402


def main(epic: str = "P1A", story: str = "SEEDPOOL") -> int:
    code, verdict = run_merge(epic, story)
    return code


if __name__ == "__main__":
    # allow: python run_merge_gate.py P1A SEEDPOOL
    args = sys.argv[1:]
    epic = args[0] if len(args) >= 1 else "P1A"
    story = args[1] if len(args) >= 2 else "SEEDPOOL"
    sys.exit(main(epic, story))
