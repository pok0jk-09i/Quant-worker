"""Tech Lead orchestrator — the merge authority (Gen-4 runtime).

Drives a Story through the role pipeline and the four Merge Gates, then writes
a Merge裁决 (merge decision) stamped with a Trace ID.  This is the runnable
embodiment of CHARTER §3.4 / STDD §4.2: no PR merges without all four doors
green, and every verdict is traceable (Article V).

Run:
    python team/runtime/orchestrator.py --epic P1A --story SEEDPOOL
    python team/runtime/orchestrator.py --epic P1A --story SEEDPOOL --agent TL

Exit code = the four-gate verdict (0 = all doors pass, 1 = blocked).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # team/runtime -> team -> repo
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from team.runtime import registry as reg  # noqa: E402
from team.runtime import trace as tr      # noqa: E402

SPEC_DIR = ROOT / "team" / "specs"
MANIFEST = SPEC_DIR / "stories_manifest.json"


def _story_exists(epic: str, story: str) -> bool:
    if not MANIFEST.exists():
        return False
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for s in data.get("stories", []):
        if s.get("epic") == epic and s.get("story").upper() == story.upper():
            return True
    return False


def run_merge(epic: str, story: str, agent: str = "TechLead") -> tuple[int, dict]:
    """Execute the four Merge Gates for a Story and emit a Merge裁决.

    Returns ``(exit_code, report_dict)``.
    """
    from team.gates import run_all   # imported lazily so package import is cheap

    tid = tr.log(epic, story, "TL", "decision",
                 f"orchestrator: begin merge for story {story} (epic {epic})")
    print(f"[orchestrator] Trace ID = {tid}")

    if not _story_exists(epic, story):
        print(f"[orchestrator][WARN] story {epic}/{story} not in {MANIFEST.name}; "
              f"门① may flag it. Proceeding with gate run.")

    print(f"[orchestrator] pipeline: {' -> '.join(reg.PIPELINE_ORDER)}")
    print(f"[orchestrator] gates: {' | '.join(reg.GATES)}")

    # ── Run the four doors (门① -> 门② -> 门③ -> 门④) ──
    gate_code, gate_report = run_all.run(trace_id=tid, epic=epic, story=story)

    allowed = gate_code == 0
    decision = "ALLOWED" if allowed else "BLOCKED"
    tr.log(epic, story, "TL", "gate",
           f"four-door verdict={'PASS' if allowed else 'FAIL'} -> {decision}",
           trace_id=tid)

    merge_verdict = {
        "trace_id": tid,
        "epic": epic,
        "story": story,
        "decision": decision,
        "merge_allowed": allowed,
        "gates": gate_report,
        "pipeline": reg.PIPELINE_ORDER,
        "generated_by": "team/runtime/orchestrator.py",
    }
    out_path = SPEC_DIR / f"merge_gate_{story}.json"
    out_path.write_text(json.dumps(merge_verdict, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"[orchestrator] Merge裁决 -> {out_path}  ({decision})")
    return gate_code, merge_verdict


def main() -> int:
    ap = argparse.ArgumentParser(description="Tech Lead merge orchestrator (Gen-4)")
    ap.add_argument("--epic", required=True, help="epic id, e.g. P1A")
    ap.add_argument("--story", required=True, help="story id, e.g. SEEDPOOL")
    ap.add_argument("--agent", default="TechLead")
    args = ap.parse_args()
    code, _ = run_merge(args.epic, args.story, args.agent)
    return code


if __name__ == "__main__":
    sys.exit(main())
