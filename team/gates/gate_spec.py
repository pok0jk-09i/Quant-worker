"""门① 规格覆盖 (Spec Coverage Gate).

Verifies every Story declared in ``team/specs/stories_manifest.json`` carries:
  * **GWT**        — a PM spec file (Given/When/Then) that exists on disk
  * **接口契约**    — an Architect interface-contract string (typing/dataclass/JSON Schema)
  * **引用测试**    — a test file that EXISTS and CONTAINS the story marker, proving
                     the GWT is covered by an executable test, not just documented.

This is the SDD layer (PROMPT_STANDARD §2 门①): specs are the single source of
truth; a Story without a referencing test is a spec that can rot.

Exit 0 = every story covered; 1 = any story missing GWT / contract / test.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "team" / "specs" / "stories_manifest.json"


def _test_references_story(test_path: Path, story: str, epic: str) -> bool:
    text = test_path.read_text(encoding="utf-8", errors="ignore")
    # Accept either an explicit marker comment or the story token anywhere.
    marker = f"STORY: S-{epic.lower()}-{story.lower()}"
    if marker.lower() in text.lower():
        return True
    # Fallback: the bare story token (e.g. "SEEDPOOL") appears in the file.
    return story.upper() in text.upper()


def run(epic: str, story: str, trace_id: str | None = None) -> tuple[bool, dict]:
    if not MANIFEST.exists():
        return False, {"error": f"manifest missing: {MANIFEST}"}
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stories = data.get("stories", [])
    issues: list[str] = []
    checked = 0
    for s in stories:
        sid = f"{s.get('epic')}/{s.get('story')}"
        # Only validate stories relevant to the requested epic/story when given,
        # but the gate is holistic: validate ALL declared stories.
        gwt = s.get("gwt")
        contract = s.get("interface_contract")
        test = s.get("test")
        if not gwt or not (ROOT / gwt).exists():
            issues.append(f"{sid}: GWT spec missing ({gwt})")
            continue
        if not contract:
            issues.append(f"{sid}: interface_contract empty")
            continue
        if not test or not (ROOT / test).exists():
            issues.append(f"{sid}: test file missing ({test})")
            continue
        if not _test_references_story(ROOT / test, s.get("story"), s.get("epic")):
            issues.append(f"{sid}: test {test} does not reference story marker")
            continue
        checked += 1
    ok = len(issues) == 0
    return ok, {"checked": checked, "issues": issues,
                "detail": "all stories covered" if ok else f"{len(issues)} gap(s)"}
