"""Candidate Submitter — tests and submits candidates from candidate_generator.py.

Reads candidates.json, runs simulations, checks IS metrics and daily-return
correlation against existing ACTIVE alphas, and submits qualifying candidates.

Usage:
    cd <skill-dir>
    pyenv exec python scripts/candidate_submitter.py

Output:
    candidate_submit_results.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import numpy as np
import requests
from requests.auth import HTTPBasicAuth

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CANDIDATES_PATH = SKILL_DIR / "candidates.json"
ALPHA_DB_PATH = SKILL_DIR / "alpha_db.json"
RESULTS_PATH = SKILL_DIR / "candidate_submit_results.json"
CREDENTIAL_PATH = SKILL_DIR / "credential.txt"

# ── Resilience infrastructure ─────────────────────────────────────────
# ResilientSession replaces the ad-hoc _request_with_retry with retry +
# jitter + circuit breaker + body-preserving responses. submit_gate
# blocks region-specific hard-check failures (e.g. IND CONCENTRATED_WEIGHT)
# BEFORE we burn a submission. Imported lazily so a missing infra package
# degrades to the legacy path rather than crashing the submitter.
try:
    if str(SCRIPT_DIR.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR.parent))
    from core.infrastructure.resilient_http import ResilientSession, HttpResult
    from core.infrastructure.submit_gate import (
        gate_submission,
        largest_universe_size,
        default_sub_size,
    )
    from core.infrastructure.expression_types import (
        validate_expression,
        load_field_types,
    )
    from core.infrastructure.timeout_field_guard import (
        is_timeout_prone,
        timeout_prone_fields_in,
    )
    from core.infrastructure import thresholds_config as _tc

    _HAS_INFRA = True
except Exception:  # pragma: no cover
    ResilientSession = None  # type: ignore[assignment]
    HttpResult = None  # type: ignore[assignment]
    gate_submission = None  # type: ignore[assignment]
    validate_expression = None  # type: ignore[assignment]
    load_field_types = None  # type: ignore[assignment]
    is_timeout_prone = None  # type: ignore[assignment]
    timeout_prone_fields_in = None  # type: ignore[assignment]
    _tc = None  # type: ignore[assignment]
    _HAS_INFRA = False


API_BASE = "https://api.worldquantbrain.com"
HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json",
}

# ── FINAL SUBMISSION GATE ─────────────────────────────────────────
# These are the OUTPUT quality thresholds.  Only variants that clear
# this bar get submitted to BRAIN.  The parent pool is much wider
# (see candidate_generator.py).  Values are sourced from
# core.infrastructure.thresholds_config (official BRAIN hard lines +
# our stricter internal floor) -- single source of truth, R5.
from core.infrastructure.thresholds_config import (  # noqa: E402
    passes_submission_gate,
    is_premium,
)

if _tc is not None:
    FITNESS_THRESHOLD = _tc.SUBMIT_FITNESS_FLOOR       # 1.0 (BRAIN min 1.0)
    SHARPE_THRESHOLD = _tc.SUBMIT_SHARPE_FLOOR         # 1.25 (BRAIN min 1.25)
    MAX_TURNOVER = _tc.SUBMIT_TURNOVER_MAX             # 0.70 (BRAIN max 0.70)
    MAX_DAILY_RETURN_CORRELATION = _tc.SELF_CORR_MAX   # 0.7
else:  # pragma: no cover - infra missing: keep last-known safe values
    FITNESS_THRESHOLD = 1.5
    SHARPE_THRESHOLD = 1.5
    MAX_TURNOVER = 0.30
    MAX_DAILY_RETURN_CORRELATION = 0.7
FINAL_SELF_CORR_THRESHOLD = 0.5          # Final gate: only submit if max_corr < this

# Rate limiting
SIMULATION_DELAY = 3   # seconds between simulations (single-threaded fallback)
POLL_INTERVAL = 8      # seconds between poll checks
POLL_TIMEOUT = 600     # seconds max poll time (BRAIN sims can take 3-5 min)
SUBMIT_CHECK_INTERVAL = 10  # seconds
SUBMIT_CHECK_COUNT = 30      # max checks
MAX_CONCURRENT = 3           # max concurrent simulations


def load_credentials() -> tuple[str, str]:
    env_user = os.getenv("WQ_BRAIN_USERNAME")
    env_password = os.getenv("WQ_BRAIN_PASSWORD")
    if env_user and env_password:
        return env_user, env_password
    candidates = [CREDENTIAL_PATH, Path.cwd() / "credential.txt"]
    for p in candidates:
        if p.exists():
            username, password = json.loads(p.read_text(encoding="utf-8"))
            return str(username), str(password)
    raise FileNotFoundError("BRAIN credentials not found.")


class _Resp:
    """Response shim so legacy call sites (resp.status_code / .headers /
    .json() / .text / .ok) keep working on top of HttpResult."""

    def __init__(self, status_code, text, headers, json_data, ok):
        self.status_code = status_code
        self.text = text
        self.headers = headers
        self._json = json_data
        self.ok = ok

    def json(self):
        if self._json is None:
            raise ValueError("No JSON in response")
        return self._json


def create_session() -> "ResilientSession":
    username, password = load_credentials()
    if not _HAS_INFRA or ResilientSession is None:
        # Legacy fallback (infra missing) — keep the old behaviour.
        session = requests.Session()
        session.auth = HTTPBasicAuth(username, password)
        session.headers.update(HEADERS)
        resp = session.post(f"{API_BASE}/authentication")
        if resp.status_code != 201:
            raise RuntimeError(f"Auth failed: {resp.status_code}")
        print(f"Authenticated: {resp.status_code}")
        return session  # type: ignore[return-value]
    sess = ResilientSession(username, password)
    res = sess.authenticate()
    if not res or res.status_code != 201:
        raise RuntimeError(f"Auth failed: {res.status_code if res else 'network'}")
    print("Authenticated: 201")
    return sess


def reauth_if_needed(session: requests.Session) -> bool:
    try:
        resp = session.get(f"{API_BASE}/users/self", timeout=10)
        if resp.status_code == 200:
            return False
        if resp.status_code != 401:
            return False
    except Exception:
        pass
    try:
        resp = session.post(f"{API_BASE}/authentication", timeout=30)
        if resp.status_code == 201:
            print("Re-authenticated: 201")
            return True
    except Exception:
        pass
    return False


def _request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    json: dict | None = None,
    max_rate_limit_retries: int = 50,
    timeout: tuple = (10, 30),
) -> _Resp | None:
    """HTTP request with resilience.

    When the resilience infrastructure is available the actual work is
    delegated to :class:`ResilientSession` (exponential backoff + full
    jitter + circuit breaker + body-preserving). The result is wrapped in
    a :class:`_Resp` shim so every legacy call site keeps working.

    The legacy code path is retained only as a fallback when infra is
    missing; it is no longer the primary implementation.
    """
    if _HAS_INFRA and ResilientSession is not None and isinstance(session, ResilientSession):
        path = url[len(API_BASE):] if url.startswith(API_BASE) else url
        try:
            if method.upper() == "GET":
                r = session.get(path)
            else:
                r = session.post(path, json=json)
        except Exception:  # noqa: BLE001
            return _Resp(None, "", {}, None, False)
        return _Resp(
            status_code=r.status_code,
            text=r.raw_text,
            headers=r.headers,
            json_data=r.body,
            ok=r.ok,
        )

    # ── Legacy fallback (infra unavailable) ──────────────────────────
    rate_limit_attempts = 0
    for attempt in range(max_rate_limit_retries + 1):
        try:
            if method.upper() == "GET":
                resp = session.get(url, timeout=timeout)
            else:
                resp = session.post(url, json=json, timeout=timeout)

            if resp.status_code == 429:
                rate_limit_attempts += 1
                if rate_limit_attempts > max_rate_limit_retries:
                    return _Resp(resp.status_code, resp.text, dict(resp.headers), _safe_json_legacy(resp), resp.ok)
                retry_after_raw = resp.headers.get("Retry-After", "5")
                try:
                    retry_after = min(int(retry_after_raw), 60)
                except (ValueError, TypeError):
                    retry_after = 5
                backoff = min(retry_after * (2 ** (rate_limit_attempts - 1)), 120)
                print(f"[429] {method} {url} — waiting {backoff}s", flush=True)
                time.sleep(backoff)
                continue

            if resp.status_code == 401:
                if reauth_if_needed(session):
                    print(f"[401] re-authenticated, retrying {url}", flush=True)
                    continue
                return _Resp(resp.status_code, resp.text, dict(resp.headers), _safe_json_legacy(resp), resp.ok)

            return _Resp(resp.status_code, resp.text, dict(resp.headers), _safe_json_legacy(resp), resp.ok)

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < max_rate_limit_retries:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def _safe_json_legacy(resp):
    try:
        return resp.json()
    except Exception:
        return None


def load_candidates() -> list[dict]:
    if not CANDIDATES_PATH.exists():
        return []
    return json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))


def load_alpha_db() -> dict:
    if not ALPHA_DB_PATH.exists():
        return {"alphas": {}}
    return json.loads(ALPHA_DB_PATH.read_text(encoding="utf-8"))


def build_payload(expr: str, settings: dict) -> dict:
    return {
        "type": "REGULAR",
        "settings": {
            "instrumentType": settings.get("instrumentType", "EQUITY"),
            "region": settings.get("region", "USA"),
            "universe": settings.get("universe", "TOP3000"),
            "delay": settings.get("delay", 1),
            "decay": settings.get("decay", 0),
            "neutralization": settings.get("neutralization", "SUBINDUSTRY"),
            "truncation": settings.get("truncation", 0.08),
            "pasteurization": "ON",
            "unitHandling": "VERIFY",
            "nanHandling": "ON",
            "maxTrade": "OFF",
            "maxPosition": "OFF",
            "language": "FASTEXPR",
            "visualization": False,
        },
        "regular": expr,
    }


def simulate_alpha(session: requests.Session, idx: int, candidate: dict) -> dict:
    """Submit alpha for simulation, return simulation info."""
    payload = build_payload(
        candidate["expression"],
        candidate.get("settings", {}),
    )
    print(f"\n[{idx}] Simulating: {candidate['expression'][:60]}...")
    print(f"    Settings: decay={candidate['settings'].get('decay')}, "
          f"neut={candidate['settings'].get('neutralization')}, "
          f"trunc={candidate['settings'].get('truncation')}")
    resp = _request_with_retry(session, "POST", f"{API_BASE}/simulations", json=payload)
    if resp is None:
        return {"error": "all retries exhausted", "status_code": None}
    print(f"    POST /simulations -> {resp.status_code}")
    if resp.status_code != 201:
        return {"error": resp.text[:500], "status_code": resp.status_code}
    location = resp.headers.get("Location", "")
    sim_id = location.rstrip("/").split("/")[-1]
    return {"simulation_id": sim_id}


def poll_simulation(session: requests.Session, sim_id: str, timeout: int = POLL_TIMEOUT) -> dict:
    """Poll simulation until COMPLETE or timeout."""
    print(f"    Polling {sim_id}...")
    start = time.time()
    last_progress = -1
    last_heartbeat = time.time()  # for "still alive" messages
    while time.time() - start < timeout:
        resp = _request_with_retry(session, "GET", f"{API_BASE}/simulations/{sim_id}")
        if resp is None or resp.status_code != 200:
            time.sleep(POLL_INTERVAL)
            continue
        data = resp.json()
        status = data.get("status", "")
        progress = data.get("progress")
        if status == "COMPLETE":
            alpha_id = data.get("alpha")
            print(f"    Alpha ID: {alpha_id}")
            return {"status": "COMPLETE", "alpha_id": alpha_id, "sim_data": data}
        if status in ("ERROR", "FAILED"):
            return {"status": "ERROR", "sim_data": data}
        # No status key + has progress → still running (BRAIN shows progress 0-1)
        if not status and progress is not None:
            pct = int(progress * 100)
            now_ts = time.time()
            if pct != last_progress:
                print(f"    Sim progress: {pct}%")
                last_progress = pct
                last_heartbeat = now_ts
            elif now_ts - last_heartbeat >= 60:
                # Progress stalled — emit a heartbeat so panel doesn't look frozen
                print(f"    Still waiting (progress unchanged at {pct}%, {int((time.time()-start)/60)}m elapsed)", flush=True)
                last_heartbeat = now_ts
        time.sleep(POLL_INTERVAL)
    return {"status": "TIMEOUT", "simulation_id": sim_id}


def get_alpha_metrics(session: requests.Session, alpha_id: str) -> dict:
    resp = _request_with_retry(session, "GET", f"{API_BASE}/alphas/{alpha_id}")
    if resp is not None and resp.status_code == 200:
        return resp.json()
    return {}


def fetch_pnl(session: requests.Session, alpha_id: str) -> list[float]:
    """Fetch cumulative PnL recordset (same logic as evolve_skill.py)."""
    try:
        resp = _request_with_retry(session, "GET", f"{API_BASE}/alphas/{alpha_id}/recordsets/pnl")
    except Exception:
        return []
    if resp is None or resp.status_code != 200 or not resp.text.strip():
        return []
    try:
        data = resp.json()
    except Exception:
        return []
    schema = data.get("schema", {})
    props = schema.get("properties", [])
    if isinstance(props, list):
        date_idx = next(
            (i for i, p in enumerate(props) if p.get("name", "").lower() == "date"), 0
        )
        pnl_idx = next(
            (i for i, p in enumerate(props) if p.get("name", "").lower() in ("pnl", "cum_pnl", "returns", "ret")), 1
        )
    else:
        date_idx = next((v["index"] for k, v in props.items() if k.lower() == "date"), 0)
        pnl_idx = next(
            (v["index"] for k, v in props.items() if k.lower() in ("pnl", "cum_pnl", "returns", "ret")), 1
        )
    records = sorted(data.get("records", []), key=lambda r: r[date_idx])
    out: list[float] = []
    for row in records:
        rec = row[0] if isinstance(row, list) and len(row) == 1 and isinstance(row[0], list) else row
        try:
            out.append(float(rec[pnl_idx]))
        except Exception:
            continue
    return out


def daily_returns(cum_pnl: list[float]) -> list[float]:
    return [cum_pnl[i + 1] - cum_pnl[i] for i in range(len(cum_pnl) - 1)]


def check_daily_return_correlation(
    new_pnl: list[float], db: dict, min_records: int = 50
) -> tuple[dict | None, float]:
    """Check daily-return correlation against all ACTIVE alphas in DB.

    Returns (highest_match or None, max_corr_value).
    max_corr is always populated so every result file entry shows the
    exact local self-correlation number, not just pass/fail.

    SKILL.md Section 8.3: correlation >= 0.7 means too similar.
    """
    if len(new_pnl) < min_records + 1:
        return None, 0.0
    new_ret = np.array(daily_returns(new_pnl))
    best_match: dict | None = None
    max_corr = 0.0
    for old_id, old in db.get("alphas", {}).items():
        if old.get("status") != "ACTIVE" or not old.get("pnl"):
            continue
        old_ret = np.array(daily_returns(old["pnl"]))
        if len(new_ret) != len(old_ret):
            continue
        corr = float(np.corrcoef(new_ret, old_ret)[0, 1])
        abs_c = abs(corr)
        if abs_c > max_corr:
            max_corr = abs_c
            best_match = {
                "alpha_id": old_id,
                "corr": corr,
                "sharpe": old.get("sharpe"),
            }
    return best_match, max_corr


def is_already_submitted(metrics: dict) -> bool:
    status = str(metrics.get("status") or "").upper()
    stage = str(metrics.get("stage") or "").upper()
    if status == "ACTIVE" or stage == "OS":
        return True
    return bool(metrics.get("dateSubmitted"))


def submit_if_passed(session: requests.Session, alpha_id: str) -> dict:
    print(f"    Submitting alpha {alpha_id}...")
    sub = _request_with_retry(session, "POST", f"{API_BASE}/alphas/{alpha_id}/submit")
    if sub is None:
        return {"submitted": False, "status_code": None, "text": "all retries exhausted"}
    print(f"    POST /alphas/{alpha_id}/submit -> {sub.status_code}")
    if sub.status_code not in (200, 201):
        # Preserve the BRAIN response BODY so a 403 (region hard-check
        # rejection) is diagnosable instead of silently discarded.
        return {"submitted": False, "status_code": sub.status_code, "text": sub.text}

    last_alpha: dict = {}
    pending_checks: list[str] = []
    for _ in range(SUBMIT_CHECK_COUNT):
        time.sleep(SUBMIT_CHECK_INTERVAL)
        resp = _request_with_retry(session, "GET", f"{API_BASE}/alphas/{alpha_id}")
        if resp is None or resp.status_code != 200:
            continue
        alpha = resp.json()
        last_alpha = alpha
        status = alpha.get("status")
        print(f"    Alpha status: {status}")
        # Capture BRAIN's actual pending checks so we know what's still in flight
        checks = alpha.get("is", {}).get("checks", [])
        pending_checks = [c.get("name") for c in checks if c.get("result") == "PENDING"]
        if status == "ACTIVE":
            return {"submitted": True, "status": "ACTIVE", "alpha": alpha}
        sc = next((c for c in checks if c.get("name") == "SELF_CORRELATION"), {})
        if sc.get("result") == "FAIL":
            return {"submitted": True, "status": alpha.get("status"), "self_correlation": "FAIL"}
        # Any other check failure (LIQUIDITY, DATA, CAPACITY, etc.)
        # means the alpha will never become ACTIVE. Don't keep polling.
        any_fail = any(
            c.get("result") == "FAIL"
            for c in checks
            if isinstance(c, dict) and c.get("name") != "SELF_CORRELATION"
        )
        if any_fail:
            failed = [c.get("name") for c in checks if c.get("result") == "FAIL"]
            return {"submitted": False, "status": "CHECK_FAILED", "failed_checks": failed}
    # BRAIN returns UNSUBMITTED while is.checks are still PENDING.
    # Surface the actual BRAIN status + which checks are still in flight.
    brain_status = last_alpha.get("status", "UNKNOWN") if last_alpha else "UNKNOWN"
    return {
        "submitted": True,
        "status": brain_status,
        "pending_checks": pending_checks,
        "alpha": last_alpha,
    }


def main():
    create_session()
    candidates = load_candidates()
    if not candidates:
        print("No candidates found. Exiting.")
        RESULTS_PATH.write_text("[]", encoding="utf-8")
        return 0

    # Dedup: skip candidates whose expression+settings combo was already
    # tried in a previous cycle. This prevents burning BRAIN sim slots on
    # deterministic repeats.
    prev_tried: set[tuple[str, str]] = set()
    if RESULTS_PATH.exists():
        try:
            prev = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
            for r in prev:
                c = r.get("candidate", {})
                expr = c.get("expression", "")
                settings_key = json.dumps(c.get("settings", {}), sort_keys=True)
                if expr:
                    prev_tried.add((expr, settings_key))
        except Exception:
            pass

    deduped = []
    for c in candidates:
        key = (c.get("expression", ""), json.dumps(c.get("settings", {}), sort_keys=True))
        if key in prev_tried:
            print(f"  SKIP (previously submitted): {c.get('expression','')[:50]}...")
            continue
        deduped.append(c)

    print(f"Loaded {len(candidates)} candidates from {CANDIDATES_PATH}")
    print(f"After dedup: {len(deduped)} new candidates (skipped {len(candidates)-len(deduped)} repeats)")
    if not deduped:
        print("All candidates already submitted. Nothing to do.")
        return 0
    candidates = deduped

    # ── Guidance-informed candidate ordering & pruning ────────────────
    # Read the same generation_guidance.json that candidate_generator
    # wrote, so candidate_submitter can (a) evaluate high-quality cluster
    # candidates first, and (b) skip candidates whose expression core
    # matches a confirmed-exhausted pattern (saving BRAIN API quota).
    GUIDANCE_PATH = SKILL_DIR / "generation_guidance.json"
    guidance: dict | None = None
    if GUIDANCE_PATH.exists():
        try:
            guidance = json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    if guidance:
        cluster_stats = guidance.get("cluster_stats", {})
        if cluster_stats:
            # Build cluster → quality score map for candidate ordering
            cluster_score = {
                c: stats.get("sharpe_median", 0.1)
                for c, stats in cluster_stats.items()
            }
            # Resolve each candidate's cluster and assign a quality score
            import sys as _sys
            _sys.path.insert(0, str(SCRIPT_DIR))
            from evolve_skill import classify_alpha as _cf2  # type: ignore[import]
            for c in candidates:
                expr = c.get("expression", "")
                cluster = _cf2(expr, c.get("settings", {})).split("-")[0] or "other"
                c["_cluster"] = cluster
                c["_quality"] = cluster_score.get(cluster, 0.05)
            # Sort: higher quality first.  Within same quality, preserve
            # original order so dedup/exploration ordering isn't lost.
            candidates.sort(key=lambda c: -(c.get("_quality", 0)))

        # Prune confirmed-exhausted patterns to save BRAIN quota
        exhausted = guidance.get("exhausted_patterns", [])
        blocked_cores = {
            ep["pattern"]
            for ep in exhausted
            if ep.get("exhaustion_level") == "confirmed"
            and ep.get("action") == "block_systematic_scan"
        }
        if blocked_cores:
            import re as _re2
            def _core(expr: str) -> str:
                c = _re2.sub(r'\b\d+\b', '*', expr)
                depth = 0
                for i, ch in enumerate(c):
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                    elif depth == 0 and ch == ',':
                        c = c[:i]
                        break
                return c[:120]
            before = len(candidates)
            candidates = [
                c for c in candidates
                if _core(c.get("expression", "")) not in blocked_cores
            ]
            if len(candidates) < before:
                print(f"Pruned {before - len(candidates)} confirmed-exhausted candidates")

    print(f"Running with {MAX_CONCURRENT} concurrent workers")
    db = load_alpha_db()
    results_lock = Lock()
    results: list[dict] = []

    # Pre-create sessions sequentially with delays. 8 concurrent
    # POST /authentication calls trigger BRAIN's rate-limit (400/captcha).
    # Creating them one at a time avoids this.
    session_pool: list[requests.Session] = []
    for i in range(min(MAX_CONCURRENT, len(candidates))):
        try:
            session_pool.append(create_session())
            print(f"  session {i + 1}/{min(MAX_CONCURRENT, len(candidates))} authenticated")
        except Exception as exc:
            print(f"  session {i + 1} auth failed: {exc}")
        time.sleep(1.5)  # Small gap to avoid BRAIN rate-limiting auth

    if not session_pool:
        print("No sessions available. Exiting.")
        return 1

    from queue import Queue
    _session_queue: Queue = Queue()
    for s in session_pool:
        _session_queue.put(s)

    def _get_session() -> requests.Session:
        """Thread-safe session acquisition — borrow, use, return."""
        return _session_queue.get()

    def _return_session(s: requests.Session) -> None:
        _session_queue.put(s)

    def process_one(idx: int, candidate: dict) -> dict:
        """Process a single candidate using a borrowed session (thread-safe)."""
        # R3-A: pre-simulation type safety. Runs BEFORE borrowing a session
        # (no BRAIN call, no session leak) so we never burn a simulation on a
        # type-incompatible expression (GROUP/SYMBOL/EVENT -> ts_*/arith).
        if _HAS_INFRA and validate_expression is not None:
            expr = (candidate.get("expression") or "").strip()
            if expr:
                viol = validate_expression(expr, load_field_types())
                if viol:
                    print(f"[{idx}] Skip: type_incompatible ({viol[0]})")
                    return {"idx": idx, "candidate": candidate,
                            "sim": {"status": "SKIPPED_TYPE"},
                            "submission": {"submitted": False,
                                           "reason": "type_incompatible",
                                           "violations": viol}}

        # R3-A (timeout-risk): BRAIN stalls at a fixed ~35% on specific
        # sparse/point-in-time/alternative-data fields (see timeout_field_guard).
        # Skip BEFORE borrowing a session or polling, so we never burn the
        # full 600s POLL_TIMEOUT on a guaranteed hang.  Derived from
        # candidate_submit_results.json: 14 fields were 100% timeout.
        if _HAS_INFRA and is_timeout_prone is not None:
            expr = (candidate.get("expression") or "").strip()
            if expr:
                risk = timeout_prone_fields_in(expr)
                if risk:
                    print(f"[{idx}] Skip: timeout_risk ({risk[0]})")
                    return {"idx": idx, "candidate": candidate,
                            "sim": {"status": "SKIPPED_TIMEOUT_RISK"},
                            "submission": {"submitted": False,
                                           "reason": "timeout_risk",
                                           "timeout_fields": risk}}

        session = _get_session()
        try:
            sim_data = simulate_alpha(session, idx, candidate)
            sim_id = sim_data.get("simulation_id")
            if not sim_id:
                return {"idx": idx, "candidate": candidate, "sim": sim_data}

            sim_result = poll_simulation(session, sim_id)
            alpha_id = sim_result.get("alpha_id")
            if not alpha_id:
                # R4: persist whatever in-sample metrics BRAIN returned even
                # when no alpha_id was issued (local observability of quality).
                _sim_is = (sim_result.get("sim_data", {}) or {}).get("is", {}) or {}
                return {"idx": idx, "candidate": candidate, "sim": sim_result,
                        "is_metrics": _sim_is}

            metrics = get_alpha_metrics(session, alpha_id)
            is_ = metrics.get("is", {})
            fitness = is_.get("fitness") or 0
            sharpe = is_.get("sharpe") or 0
            turnover = is_.get("turnover") or 1
            print(f"[{idx}] IS: Sharpe={sharpe:.2f} Fitness={fitness:.2f} TO={turnover*100:.2f}%")

            gate_ok, gate_reason = passes_submission_gate(is_)
            if not gate_ok:
                print(f"[{idx}] Skip: {gate_reason}")
                return {"idx": idx, "candidate": candidate, "sim": sim_result, "metrics": metrics,
                        "is_metrics": is_,
                        "submission": {"submitted": False, "reason": gate_reason,
                                       "premium": is_premium(is_)}}

            pnl = fetch_pnl(session, alpha_id)
            best_corr_match, max_corr = check_daily_return_correlation(pnl, db)
            if max_corr >= MAX_DAILY_RETURN_CORRELATION:
                print(f"[{idx}] Skip: correlation {max_corr:.4f} vs {best_corr_match['alpha_id'] if best_corr_match else '?'}")
                return {"idx": idx, "candidate": candidate, "sim": sim_result, "metrics": metrics,
                        "submission": {"submitted": False, "reason": "high_correlation",
                                       "max_corr": max_corr, "best_match": best_corr_match}}

            if is_already_submitted(metrics):
                print(f"[{idx}] Skip: already submitted ({metrics.get('status')})")
                return {"idx": idx, "candidate": candidate, "sim": sim_result, "metrics": metrics,
                        "submission": {"submitted": False, "reason": "already_submitted",
                                       "status": metrics.get("status"), "stage": metrics.get("stage")},
                        "max_corr": max_corr}

            # FINAL GATE: self-correlation must be < 0.5 to submit.
            # This is ONLY here, at the last decision point before BRAIN commit.
            if max_corr >= FINAL_SELF_CORR_THRESHOLD:
                print(f"[{idx}] Skip: self-corr {max_corr:.4f} >= {FINAL_SELF_CORR_THRESHOLD}")
                return {"idx": idx, "candidate": candidate, "sim": sim_result, "metrics": metrics,
                        "submission": {"submitted": False, "reason": "self_corr_final_gate",
                                       "max_corr": max_corr, "threshold": FINAL_SELF_CORR_THRESHOLD},
                        "max_corr": max_corr}

            # REGION GATE: do not waste a submission on alphas that BRAIN
            # will reject at the production step (region-specific hard
            # checks such as IND CONCENTRATED_WEIGHT). Evaluated from data
            # BRAIN already returned in `is.checks`/`is` — zero extra cost.
            # R1: also feed universe sizes + delay so the √252 Sub-Universe
            # formula (verified) actually executes instead of being dead code.
            settings = candidate.get("settings", {}) or {}
            if _HAS_INFRA and gate_submission is not None:
                universe = settings.get("universe")
                gate = gate_submission(
                    region=settings.get("region"),
                    universe=universe,
                    is_checks=is_.get("checks"),
                    is_metrics=is_,
                    sub_size=default_sub_size(universe),
                    largest_universe_size=largest_universe_size(universe),
                    delay=settings.get("delay", 1),
                )
                if not gate.submit_allowed:
                    print(f"[{idx}] Skip: region_gate ({gate.reason})")
                    return {"idx": idx, "candidate": candidate, "sim": sim_result, "metrics": metrics,
                            "submission": {"submitted": False, "reason": "region_gate",
                                           "detail": gate.reason,
                                           "failed_checks": gate.failed_checks},
                            "max_corr": max_corr}

            sub_result = submit_if_passed(session, alpha_id)
            return {"idx": idx, "candidate": candidate, "sim": sim_result, "metrics": metrics,
                    "is_metrics": is_,
                    "premium": is_premium(is_),
                    "submission": sub_result, "max_corr": max_corr}
        except Exception as e:
            try:
                print(f"[{idx}] Exception: {e}", flush=True)
            except OSError:
                # Windows pipe + non-ASCII exception message → OSError 22
                sys.stderr.write(f"[{idx}] Exception: {e}\n")
                sys.stderr.flush()
            return {"idx": idx, "candidate": candidate, "error": str(e)}
        finally:
            _return_session(session)

    with ThreadPoolExecutor(max_workers=len(session_pool)) as executor:
        futures = {
            executor.submit(process_one, i + 1, c): c
            for i, c in enumerate(candidates)
        }
        for future in as_completed(futures):
            result = future.result()
            with results_lock:
                results.append(result)

    # Sort by idx so the output file is ordered
    results.sort(key=lambda r: r.get("idx", 0))
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to: {RESULTS_PATH}")

    submitted = [r for r in results if r.get("submission", {}).get("status") == "ACTIVE"]
    skipped_threshold = [r for r in results if r.get("submission", {}).get("reason") == "metrics_threshold"]
    skipped_corr = [r for r in results if r.get("submission", {}).get("reason") == "high_correlation"]
    errors = [r for r in results if "error" in r]
    # Correlation stats for every candidate that had PnL checked
    corr_values = [r.get("max_corr") for r in results if r.get("max_corr") is not None]
    print("\n=== Summary ===")
    print(f"Total: {len(candidates)} | Submitted ACTIVE: {len(submitted)}")
    print(f"Skipped threshold: {len(skipped_threshold)} | Skipped corr: {len(skipped_corr)} | Errors: {len(errors)}")
    if corr_values:
        print(f"Self-correlation (max): mean={np.mean(corr_values):.4f} median={np.median(corr_values):.4f} "
              f"min={min(corr_values):.4f} max={max(corr_values):.4f} n={len(corr_values)}")
        above = sum(1 for c in corr_values if c >= MAX_DAILY_RETURN_CORRELATION)
        print(f"  ≥{MAX_DAILY_RETURN_CORRELATION}: {above}/{len(corr_values)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
