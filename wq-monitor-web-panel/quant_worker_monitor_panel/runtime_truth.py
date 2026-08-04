from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_SOURCE_KINDS = {
    "project_runtime_state": "authority",
    "batch_submit_results": "authority",
    "project_runtime_log": "authority",
    "adapter_state": "derived",
    "panel_state": "display_only",
}


def classify_state_source(name: str) -> str:
    return STATE_SOURCE_KINDS.get(str(name or "").strip(), "unknown")


def load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_submit_results_payload(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def submit_results_are_fresh_for_runtime(
    *,
    submit_results_updated_at: str,
    runtime_updated_at: str,
) -> bool:
    submit_dt = _parse_iso_datetime(submit_results_updated_at)
    runtime_dt = _parse_iso_datetime(runtime_updated_at)
    if submit_dt is None or runtime_dt is None:
        return False
    return submit_dt >= runtime_dt


# Fields that, if mismatched between authority (project_runtime) and
# derived (adapter.project_state), indicate a real conflict that should
# be surfaced to operators. Other fields are allowed to drift (timestamps,
# cycle_count, etc. are expected to lag).
RECONCILIATION_FIELDS = (
    "last_leaf_job",
    "project_health",
    "last_error",
    "mode",
    "submit_status",
    "submit_failure_kind",
    "submission_summary",
)

# Maximum age (in seconds) of the derived copy before it should be treated
# as stale. Currently the adapter writes every 30s, so >120s means the
# adapter process has stopped writing.
DERIVED_STATE_STALE_SECONDS = 120


def reconcile_authority_derived(
    *,
    authority: dict[str, Any] | None,
    derived: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compare authority (project_runtime_state) and derived (adapter.project_state).

    Returns a dict with:
      - conflicts: list of {field, authority, derived} for fields that disagree
      - stale: bool — True if derived copy is older than DERIVED_STATE_STALE_SECONDS
      - derived_age_seconds: int — how old the derived copy is
      - recommended_authority: which side the UI should trust for each conflict
    """
    auth = authority if isinstance(authority, dict) else {}
    der = derived if isinstance(derived, dict) else {}
    current = now or datetime.now()

    conflicts: list[dict[str, Any]] = []
    for field in RECONCILIATION_FIELDS:
        a_val = auth.get(field)
        d_val = der.get(field)
        if a_val == d_val:
            continue
        # Both empty / falsy — no real conflict
        if not a_val and not d_val:
            continue
        conflicts.append({
            "field": field,
            "authority": a_val,
            "derived": d_val,
            "recommended_authority": "authority",  # always trust the source
        })

    # Staleness check
    der_updated = _parse_iso_datetime(der.get("heartbeat_at", "") or der.get("updated_at", ""))
    derived_age = -1
    stale = False
    if der_updated is None:
        stale = True
    else:
        derived_age = int((current - der_updated).total_seconds())
        stale = derived_age > DERIVED_STATE_STALE_SECONDS

    return {
        "conflicts": conflicts,
        "stale": stale,
        "derived_age_seconds": derived_age,
        "check_at": current.isoformat(),
    }
