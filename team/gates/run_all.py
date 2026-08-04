"""Four Merge Gates runner — chains 门① -> 门② -> 门③ -> 门④ (Gen-4).

Invoked by the Tech Lead orchestrator.  Runs every door (continues past a
failed door so the full verdict is visible), records each, writes
``team/qa_gate_report.json`` (the merge-gate report, stamped with the Trace ID),
and returns ``(exit_code, report)``.

Any door failing => PR red (CHARTER §3.4 / STDD §4.2).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from team.gates import gate_spec, gate_tests, gate_contract, gate_qa  # noqa: E402

REPORT_PATH = ROOT / "team" / "qa_gate_report.json"

# Door order is fixed by STDD §4.2.
_DOORS = [
    ("门① 规格覆盖", gate_spec),
    ("门② 测试通过", gate_tests),
    ("门③ 契约通过", gate_contract),
    ("门④ 独立评估", gate_qa),
]


def run(trace_id: str, epic: str, story: str,
        mutation_config: str | None = None) -> tuple[int, dict]:
    doors: dict[str, dict] = {}
    print("=" * 70)
    print(f"FOUR MERGE GATES  |  trace={trace_id}  epic={epic}  story={story}")
    print("=" * 70)
    for name, mod in _DOORS:
        try:
            ok, detail = mod.run(epic=epic, story=story, trace_id=trace_id)
        except Exception as exc:  # gate must never crash the merge decision
            ok, detail = False, f"EXCEPTION: {exc!r}"
        doors[name] = {"ok": bool(ok), "detail": detail}
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = all(d["ok"] for d in doors.values())
    report = {"trace_id": trace_id, "epic": epic, "story": story,
              "doors": doors, "merge_allowed": all_ok}
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    print("-" * 70)
    print(f"OVERALL: {'ALL DOORS PASS — SAFE TO MERGE' if all_ok else 'GATE FAILED — DO NOT MERGE'}")
    print(f"Report -> {REPORT_PATH}")
    return (0 if all_ok else 1), report


if __name__ == "__main__":
    from team.runtime import trace as tr
    tid = tr.make_trace_id("P1A", "GATES", "TL")
    code, _ = run(tid, "P1A", "GATES")
    sys.exit(code)
