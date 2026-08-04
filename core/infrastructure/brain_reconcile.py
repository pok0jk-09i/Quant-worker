"""Reconcile the local alpha database with BRAIN platform truth.

THE PROBLEM
-----------
Local ``alpha_db.json`` had drifted from reality: it contained 10 records
marked ``ACTIVE`` that do not exist on BRAIN at all (ghost records — most
likely a stale bulk snapshot from an era when the account had fewer than
1000 alphas and pagination never re-fetched them). Relying on local
status to judge "did we ship anything" produced a false "10 ACTIVE"
conclusion.

THE FIX
-------
A single, idempotent reconciliation pass:

1. Paginate BRAIN ``/users/self/alphas`` (limit 200, follow ``next``) to
   build ``{alpha_id: platform_status}``.
2. For every local alpha:
     * If it exists on the platform -> overwrite local ``status`` with the
       platform truth (platform is authoritative).
     * If it does NOT exist on the platform but local says ACTIVE ->
       it is a ghost. We flag it (set status to ``"GHOST"`` and record
       ``platform_exists=False``) so it can never again masquerade as a
       shipped alpha. We do NOT silently delete (preserves forensic data).
3. Atomic write-back (temp + replace) to avoid corrupting the DB if the
   process is interrupted.

The function returns a structured :class:`ReconcileReport` for logging.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Import the resilient client. If run standalone, ensure the research root
# is importable.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.infrastructure.resilient_http import ResilientSession, API_BASE  # noqa: E402


@dataclass
class ReconcileReport:
    local_total: int = 0
    platform_total: int = 0
    corrected: int = 0            # local status changed to match platform
    ghosts_flagged: int = 0       # local ACTIVE but absent on platform
    missing_locally: int = 0      # on platform but not in local db
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"local={self.local_total} platform={self.platform_total} "
            f"corrected={self.corrected} ghosts_flagged={self.ghosts_flagged} "
            f"missing_locally={self.missing_locally} errors={len(self.errors)}"
        )


def _fetch_platform_map(session: ResilientSession, limit: int = 200) -> dict[str, str]:
    """Paginate /users/self/alphas -> {alpha_id: status}."""
    mapping: dict[str, str] = {}
    next_url: str | None = f"{API_BASE}/users/self/alphas?limit={limit}"
    pages = 0
    prev_url: str | None = None
    while next_url:
        pages += 1
        if pages > 50:  # safety: hard cap at 10k alphas
            break
        result = session.get(_strip_base(next_url))
        if not result or result.status_code != 200:
            raise RuntimeError(
                f"platform fetch failed: {result.status_code if result else 'network'}"
            )
        data = result.body or {}
        for a in data.get("results", []):
            aid = a.get("id")
            if aid:
                mapping[str(aid)] = str(a.get("status"))
        next_url = data.get("next")
        if next_url and next_url == prev_url:  # loop guard
            break
        prev_url = next_url
    return mapping


def _strip_base(url: str) -> str:
    if url.startswith(API_BASE):
        return url[len(API_BASE):]
    return url


def reconcile(
    db_path: Path,
    session: ResilientSession,
    *,
    save: bool = True,
) -> ReconcileReport:
    """Reconcile local ``alpha_db.json`` against BRAIN platform truth."""
    report = ReconcileReport()
    db_path = Path(db_path)
    if not db_path.exists():
        report.errors.append(f"db not found: {db_path}")
        return report

    db = json.loads(db_path.read_text(encoding="utf-8"))
    alphas = db.get("alphas", {}) if isinstance(db, dict) else {}
    report.local_total = len(alphas)

    try:
        platform = _fetch_platform_map(session)
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"platform fetch error: {exc}")
        return report

    report.platform_total = len(platform)
    changed = False

    for aid, rec in alphas.items():
        if not isinstance(rec, dict):
            continue
        plat_status = platform.get(aid)
        if plat_status is None:
            # Not on platform. If local claimed ACTIVE -> ghost.
            if rec.get("status") == "ACTIVE":
                rec["status"] = "GHOST"
                rec["platform_exists"] = False
                report.ghosts_flagged += 1
                changed = True
            continue
        # On platform -> platform is authoritative.
        if rec.get("status") != plat_status:
            rec["status"] = plat_status
            report.corrected += 1
            changed = True
        rec["platform_exists"] = True

    # Count platform alphas absent from local db (informational).
    report.missing_locally = sum(1 for aid in platform if aid not in alphas)

    if save and changed:
        _atomic_write(db_path, db)
    return report


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        tmp.replace(path)
    except OSError:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
