"""Batch submit alphas to WorldQuant BRAIN for testing.

Usage:
    cd <skill-dir>
    pyenv exec python scripts/submit_batch.py

Reads credentials from WQ_BRAIN_USERNAME/WQ_BRAIN_PASSWORD or an untracked
credential.txt (JSON array ["username", "password"]).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CREDENTIAL_PATH = SKILL_DIR / "credential.txt"
API_BASE = "https://api.worldquantbrain.com"

HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json",
}


ALPHAS = [
    {
        "expression": "group_rank(ts_rank(operating_income / equity, 126), subindustry)",
        "decay": 0,
        "truncation": 0.08,
        "neutralization": "SUBINDUSTRY",
    },
    {
        "expression": "group_rank(ts_rank(est_eps / close, 126), industry)",
        "decay": 2,
        "truncation": 0.08,
        "neutralization": "INDUSTRY",
    },
    {
        "expression": "group_rank(ts_rank(free_cash_flow_reported_value / equity, 126), industry)",
        "decay": 0,
        "truncation": 0.08,
        "neutralization": "INDUSTRY",
    },
    {
        "expression": "0.5 * rank(-(close / open - 1)) + 0.5 * rank(ts_rank(operating_income / equity, 126))",
        "decay": 12,
        "truncation": 0.08,
        "neutralization": "INDUSTRY",
    },
]

# -----------------------------------------------------------------------
# Submission thresholds — high-confidence only
# Both this file and SKILL.md Section 5.1 are authoritative sources.
# -----------------------------------------------------------------------
FITNESS_THRESHOLD = 1.5    # BRAIN official: >= 1.0. We use 1.5 to filter noise.
SHARPE_THRESHOLD = 1.5     # Same — final gate, not parent selection
MAX_TURNOVER = 0.20


def _check_against_thresholds(fitness: float, sharpe: float, turnover: float) -> bool:
    """Return True if the alpha meets the SKILL.md-aligned submission thresholds."""
    return fitness >= FITNESS_THRESHOLD and sharpe >= SHARPE_THRESHOLD and turnover <= MAX_TURNOVER


def _threshold_skip_reason(fitness: float, sharpe: float, turnover: float) -> str:
    failures = []
    if fitness < FITNESS_THRESHOLD:
        failures.append(f"Fitness={fitness:.2f}<{FITNESS_THRESHOLD}")
    if sharpe < SHARPE_THRESHOLD:
        failures.append(f"Sharpe={sharpe:.2f}<{SHARPE_THRESHOLD}")
    if turnover > MAX_TURNOVER:
        failures.append(f"TO={turnover*100:.1f}%>{MAX_TURNOVER*100:.0f}%")
    return "; ".join(failures)


def load_credentials() -> tuple[str, str]:
    env_user = os.getenv("WQ_BRAIN_USERNAME")
    env_password = os.getenv("WQ_BRAIN_PASSWORD")
    if env_user and env_password:
        return env_user, env_password

    candidates = [
        CREDENTIAL_PATH,
        Path.cwd() / "credential.txt",
    ]
    for p in candidates:
        if p.exists():
            username, password = json.loads(p.read_text(encoding="utf-8"))
            return str(username), str(password)
    raise FileNotFoundError(
        "BRAIN credentials not found. Set WQ_BRAIN_USERNAME/WQ_BRAIN_PASSWORD "
        'or create an untracked credential.txt with ["your_username", "your_password"].'
    )


def create_session() -> requests.Session:
    username, password = load_credentials()
    session = requests.Session()
    session.auth = HTTPBasicAuth(username, password)
    session.headers.update(HEADERS)
    resp = session.post(f"{API_BASE}/authentication")
    if resp.status_code != 201:
        raise RuntimeError(f"Auth failed: {resp.status_code} {resp.text}")
    print(f"Authenticated: {resp.status_code}")
    return session


def reauth_if_needed(session: requests.Session) -> bool:
    """Re-authenticate when the session has expired.

    Returns True if re-auth was performed, False if session is still valid.
    """
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
    timeout: tuple = (10, 60),
) -> requests.Response | None:
    """HTTP request with full retry: 429, 401, network errors.

    Returns the response on success. On 401, attempts re-auth and retries once.
    On 429, honors Retry-After header with exponential backoff up to max_rate_limit_retries.
    Returns None if all retries exhausted.
    """
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
                    return resp  # Give up but return last response for caller to handle
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
                return resp  # Re-auth failed

            return resp

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt < max_rate_limit_retries:
                time.sleep(2 ** attempt)
                continue
            return None
    return None


def build_payload(expr: str, decay: int, truncation: float, neutralization: str) -> dict:
    return {
        "type": "REGULAR",
        "settings": {
            "instrumentType": "EQUITY",
            "region": "USA",
            "universe": "TOP3000",
            "delay": 1,
            "decay": decay,
            "neutralization": neutralization,
            "truncation": truncation,
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


def submit_alpha(session: requests.Session, idx: int, alpha: dict) -> dict:
    payload = build_payload(
        alpha["expression"],
        alpha["decay"],
        alpha["truncation"],
        alpha["neutralization"],
    )
    print(f"\n[{idx}] Simulating: {alpha['expression'][:60]}...")
    resp = _request_with_retry(session, "POST", f"{API_BASE}/simulations", json=payload)
    if resp is None:
        return {"error": "all retries exhausted", "status_code": None}
    print(f"    POST /simulations -> {resp.status_code}")
    if resp.status_code != 201:
        print(f"    Error: {resp.text[:300]}")
        return {"error": resp.text[:500], "status_code": resp.status_code}
    location = resp.headers.get("Location", "")
    sim_id = location.rstrip("/").split("/")[-1]
    print(f"    Simulation ID: {sim_id}")
    return {"simulation_id": sim_id}


def poll_simulation(session: requests.Session, sim_id: str, timeout: int = 600) -> dict:
    """Poll simulation until COMPLETE, ERROR, FAILED, or timeout (default 600s).

    BRAIN returns 'status' only after completion. During active simulation,
    the response is typically {'progress': 0.35} with NO status key.
    We treat missing status + presence of 'progress' as normal in-progress.
    """
    print(f"    Polling simulation {sim_id}...")
    start = time.time()
    last_progress = -1.0
    last_heartbeat = time.time()
    while time.time() - start < timeout:
        resp = _request_with_retry(session, "GET", f"{API_BASE}/simulations/{sim_id}")
        if resp is None or resp.status_code != 200:
            status = resp.status_code if resp is not None else "None"
            print(f"    GET /simulations/{sim_id} -> {status}")
            time.sleep(8)
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

        # No status key — simulation is still running. BRAIN exposes progress
        # as a float (0-1) while the sim is active.
        if not status and progress is not None:
            pct = int(progress * 100)
            now_ts = time.time()
            if pct != last_progress:
                print(f"    Sim progress: {pct}%")
                last_progress = pct
                last_heartbeat = now_ts  # reset heartbeat
            elif now_ts - last_heartbeat >= 60:
                print(f"    Still waiting (progress unchanged at {pct}%, {int((time.time()-start)/60)}m elapsed)", flush=True)
                last_heartbeat = now_ts
            time.sleep(8)
            continue

        # Genuinely unrecognised
        print(f"    Sim status: {status} (unrecognised)")
        time.sleep(8)
        time.sleep(8)
    return {"status": "TIMEOUT", "simulation_id": sim_id}


def submit_if_passed(session: requests.Session, alpha_id: str) -> dict:
    """Submit alpha and poll until ACTIVE or SELF_CORRELATION result known."""
    print(f"    Submitting alpha {alpha_id}...")
    sub = _request_with_retry(session, "POST", f"{API_BASE}/alphas/{alpha_id}/submit")
    if sub is None:
        return {"submitted": False, "status_code": None, "text": "all retries exhausted"}
    print(f"    POST /alphas/{alpha_id}/submit -> {sub.status_code}")
    if sub.status_code not in (200, 201):
        return {"submitted": False, "status_code": sub.status_code, "text": sub.text[:300]}

    last_alpha = {}
    for _ in range(30):
        time.sleep(10)
        resp = _request_with_retry(session, "GET", f"{API_BASE}/alphas/{alpha_id}")
        if resp is None or resp.status_code != 200:
            continue
        alpha = resp.json()
        last_alpha = alpha
        status = alpha.get("status")
        print(f"    Alpha status: {status}")
        if status == "ACTIVE":
            return {"submitted": True, "status": "ACTIVE", "alpha": alpha}
        checks = alpha.get("is", {}).get("checks", [])
        sc = next((c for c in checks if c.get("name") == "SELF_CORRELATION"), {})
        if sc.get("result") == "FAIL":
            return {"submitted": True, "status": alpha.get("status"), "self_correlation": "FAIL", "alpha": alpha}
        if status == "UNSUBMITTED" and sc.get("result") == "PASS":
            # sometimes needs more time to become ACTIVE
            continue
        # Any other check failure means the alpha won't become ACTIVE
        any_fail = any(
            c.get("result") == "FAIL"
            for c in checks
            if isinstance(c, dict) and c.get("name") != "SELF_CORRELATION"
        )
        if any_fail:
            failed = [c.get("name") for c in checks if c.get("result") == "FAIL"]
            return {"submitted": False, "status": "CHECK_FAILED", "failed_checks": failed, "alpha": alpha}
    return {"submitted": True, "status": "PENDING", "alpha": last_alpha}


def get_alpha_metrics(session: requests.Session, alpha_id: str) -> dict:
    resp = _request_with_retry(session, "GET", f"{API_BASE}/alphas/{alpha_id}")
    if resp is not None and resp.status_code == 200:
        return resp.json()
    return {}


def is_already_submitted(metrics: dict) -> bool:
    status = str(metrics.get("status") or "").upper()
    stage = str(metrics.get("stage") or "").upper()
    is_checks = metrics.get("is", {}).get("checks", []) if isinstance(metrics.get("is"), dict) else []
    if status == "ACTIVE" or stage == "OS":
        return True
    if any(
        isinstance(check, dict)
        and str(check.get("name") or "").upper() == "ALREADY_SUBMITTED"
        and str(check.get("result") or "").upper() == "FAIL"
        for check in is_checks
    ):
        return True
    submitted = metrics.get("dateSubmitted")
    return bool(submitted)


def _summary_alpha_id(result: dict) -> str:
    submission = result.get("submission", {}) if isinstance(result.get("submission"), dict) else {}
    submission_alpha = submission.get("alpha")
    if isinstance(submission_alpha, dict) and submission_alpha.get("id"):
        return str(submission_alpha["id"])
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    if metrics.get("id"):
        return str(metrics["id"])
    sim = result.get("sim", {}) if isinstance(result.get("sim"), dict) else {}
    if sim.get("alpha_id"):
        return str(sim["alpha_id"])
    return "UNKNOWN"


def print_summary(results: list[dict]) -> None:
    active = [r for r in results if r.get("submission", {}).get("status") == "ACTIVE"]
    submitted_pending = [
        r for r in results
        if r.get("submission", {}).get("submitted") and r.get("submission", {}).get("status") != "ACTIVE"
    ]
    skipped = [r for r in results if r.get("submission", {}).get("submitted") is False]
    sim_errors = [r for r in results if (r.get("sim") or {}).get("status") == "ERROR"]
    request_errors = [r for r in results if "error" in r]

    print("\n=== Summary ===")
    print(f"ACTIVE: {len(active)}")
    print(f"Submitted but not ACTIVE: {len(submitted_pending)}")
    print(f"Skipped by metrics threshold: {len(skipped)}")
    print(f"Simulation errors: {len(sim_errors)}")
    print(f"Request errors: {len(request_errors)}")

    for r in active:
        m = r.get("metrics", {}).get("is", {})
        alpha_id = _summary_alpha_id(r)
        print(
            f"  ACTIVE {alpha_id}: Sharpe={m.get('sharpe',0):.2f}, "
            f"Fitness={m.get('fitness',0):.2f}, TO={m.get('turnover',0)*100:.2f}%"
        )


def main():
    # ── Read guidance for cluster-quality context ──────────────────
    guidance: dict | None = None
    guidance_path = SKILL_DIR / "generation_guidance.json"
    if guidance_path.exists():
        try:
            guidance = json.loads(guidance_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if guidance:
        cluster_stats = guidance.get("cluster_stats", {})
        print("Batch templates vs empirical cluster performance:")
        sys.path.insert(0, str(SCRIPT_DIR))
        from evolve_skill import classify_alpha as _cf3  # type: ignore[import]
        for alpha in ALPHAS:
            expr = alpha["expression"]
            cluster = _cf3(expr, alpha).split("-")[0] or "other"
            stats = cluster_stats.get(cluster, {})
            med = stats.get("sharpe_median", "?")
            print(f"  [{cluster:15s}] median Sharpe={med} ← {expr[:50]}...")
    print()

    session = create_session()
    results = []
    for i, alpha in enumerate(ALPHAS, 1):
        try:
            submit_data = submit_alpha(session, i, alpha)
            sim_id = submit_data.get("simulation_id")
            if not sim_id:
                results.append({"idx": i, "expression": alpha["expression"], "submit": submit_data, "sim": None})
                continue
            sim_result = poll_simulation(session, sim_id)
            alpha_id = sim_result.get("alpha_id")
            if not alpha_id:
                results.append({"idx": i, "expression": alpha["expression"], "sim": sim_result})
                continue
            metrics = get_alpha_metrics(session, alpha_id)
            is_ = metrics.get("is", {})
            fitness = is_.get("fitness", 0)
            sharpe = is_.get("sharpe", 0)
            turnover = is_.get("turnover", 1)
            print(f"    IS metrics: Sharpe={sharpe:.2f}, Fitness={fitness:.2f}, TO={turnover*100:.2f}%")
            if _check_against_thresholds(fitness, sharpe, turnover):
                if is_already_submitted(metrics):
                    results.append({
                        "idx": i,
                        "expression": alpha["expression"],
                        "sim": sim_result,
                        "metrics": metrics,
                        "submission": {
                            "submitted": False,
                            "reason": "already_submitted",
                            "status": metrics.get("status"),
                            "stage": metrics.get("stage"),
                        },
                    })
                    print(f"    Skip submit: already submitted ({metrics.get('status')}, {metrics.get('stage')})")
                    time.sleep(3)
                    continue
                sub_result = submit_if_passed(session, alpha_id)
                results.append({"idx": i, "expression": alpha["expression"], "sim": sim_result, "metrics": metrics, "submission": sub_result})
            else:
                reason_detail = _threshold_skip_reason(fitness, sharpe, turnover)
                print(f"    Skip submit: {reason_detail}")
                results.append({"idx": i, "expression": alpha["expression"], "sim": sim_result, "metrics": metrics, "submission": {"submitted": False, "reason": "metrics_threshold", "detail": reason_detail}})
        except Exception as e:
            print(f"[{i}] Exception: {e}")
            results.append({"idx": i, "expression": alpha["expression"], "error": str(e)})
        time.sleep(3)

    out_path = SKILL_DIR / "batch_submit_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved to: {out_path}")
    print_summary(results)


if __name__ == "__main__":
    main()
