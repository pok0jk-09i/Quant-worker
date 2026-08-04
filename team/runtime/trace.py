"""Trace ID + run ledger (Article V 可追溯, Gen-4 runtime backbone).

Trace ID format (PROMPT_STANDARD §1.6):
    TRC-<EPIC>-<STORY>-<AGENT>-<NN>
Example: TRC-P1A-SHARPE-RS-01
  EPIC   = P1A
  STORY  = SHARPE   (Story id, PM-issued, e.g. S-p1a-03 -> "SHARPE")
  AGENT  = RS        (role short code, see ROLE_SHORT)
  NN     = 01..99     (per (epic,story,agent) sequence, 2-digit)

The same Story keeps its Trace ID across role handoffs; only the <AGENT>
segment changes.  Every decision / artifact / gate verdict carries a Trace ID
so any outcome is reproducible from ``ledger.jsonl``.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# Full-role-name -> short code (2-letter, used in the Trace ID <AGENT> segment).
# Mirror registry.ROLES keys.  Short codes are what actually appear in a Trace ID.
ROLE_SHORT: dict[str, str] = {
    "TechLead": "TL", "PM": "PM", "Architect": "AR", "Researcher": "RS",
    "Backend": "BE", "Data": "DA", "QA": "QA", "SRE": "SR",
}
_SHORT_CODES = frozenset(ROLE_SHORT.values())


def _resolve_short(agent: str) -> str:
    """Accept either a full role name (TechLead) or its short code (TL);
    always return the 2-letter short code used in a Trace ID."""
    if agent in ROLE_SHORT:          # full name -> short code
        return ROLE_SHORT[agent]
    if agent in _SHORT_CODES:        # already a short code
        return agent
    raise ValueError(f"unknown agent '{agent}'; known short codes={sorted(_SHORT_CODES)}")

LEDGER_PATH = Path(__file__).resolve().parent / ".trace_ledger.jsonl"

_TRACE_RE = re.compile(r"^TRC-[A-Z0-9]+-[A-Z0-9]+-[A-Z]{2}-\d{2}$")


@dataclass
class TraceEntry:
    trace_id: str
    epic: str
    story: str
    agent: str
    seq: int
    kind: str            # decision | artifact | gate | handoff
    detail: str
    ts: float


def _next_seq(epic: str, story: str, agent: str) -> int:
    seq = 0
    if LEDGER_PATH.exists():
        for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("epic") == epic and rec.get("story") == story and rec.get("agent") == agent:
                seq = max(seq, int(rec.get("seq", 0)))
    return seq + 1


def make_trace_id(epic: str, story: str, agent: str) -> str:
    """Return a fresh Trace ID for (epic, story, agent) and reserve its seq.

    ``agent`` may be a full role name (TechLead) or its short code (TL); the
    Trace ID always embeds the 2-letter short code.
    """
    code = _resolve_short(agent)
    seq = _next_seq(epic, story, code)
    return f"TRC-{epic}-{story}-{code}-{seq:02d}"


def append(entry: TraceEntry) -> None:
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def log(epic: str, story: str, agent: str, kind: str, detail: str,
        trace_id: str | None = None) -> str:
    """Convenience: mint (or reuse) a Trace ID, append a ledger entry, return it.

    ``agent`` is normalized to its 2-letter short code so the ledger and the
    Trace ID stay consistent regardless of whether a caller passes a full role
    name or a short code.
    """
    code = _resolve_short(agent)
    if trace_id is None:
        trace_id = make_trace_id(epic, story, code)
    m = _TRACE_RE.match(trace_id)
    if not m:
        raise ValueError(f"malformed Trace ID '{trace_id}'")
    seq = int(trace_id.split("-")[-1])
    append(TraceEntry(trace_id, epic, story, code, seq, kind, detail, time.time()))
    return trace_id


def is_valid(trace_id: str) -> bool:
    return bool(_TRACE_RE.match(trace_id))


def recent(limit: int = 20) -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    lines = [line for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


if __name__ == "__main__":
    tid = log("P1A", "SEEDPOOL", "TL", "decision", "Gen-4 runtime trace self-test")
    print("minted:", tid, "valid:", is_valid(tid))
    print("recent:", recent(3))
