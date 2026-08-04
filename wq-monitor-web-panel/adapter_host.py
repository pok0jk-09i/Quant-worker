from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_worker_monitor_panel.chain_auditor import audit_workflows
from quant_worker_monitor_panel.runtime_truth import (
    classify_state_source,
    load_submit_results_payload,
    submit_results_are_fresh_for_runtime,
)
from quant_worker_monitor_panel.single_instance import SingleInstanceGuard, list_active_python_pids


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.getenv("QUANT WORKER_RESEARCH_ROOT", r"E:\Quant worker-CLEAN\wq-alpha-research"))
PROJECT_RUNTIME = PROJECT_ROOT / "project_runtime.py"
STATE_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Quant worker-Monitor"
ADAPTER_STATE_PATH = STATE_DIR / "adapter_state.json"
PROJECT_STATE_PATH = STATE_DIR / "project_runtime_state.json"
ADAPTER_LOCK_PATH = STATE_DIR / "adapter_host.lock"
HEARTBEAT_SECONDS = int(os.getenv("QUANT WORKER_ADAPTER_HEARTBEAT_SECONDS", "30"))
BOOTSTRAP_WAIT_SECONDS = float(os.getenv("QUANT WORKER_ADAPTER_BOOTSTRAP_WAIT_SECONDS", "5"))
RUN_MODE_RESEARCH = "research"
RUN_MODE_FULL = "research+submit"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_failure(error_text: str) -> str:
    text = (error_text or "").lower()
    if "invalid offset" in text:
        return "contract_mismatch"
    if "auth failed" in text or "authentication" in text or "credential" in text or "401" in text:
        return "auth"
    if "timeout" in text or "connection" in text or "429" in text or "rate limit" in text:
        return "network"
    if "no module named" in text or "filenotfounderror" in text or "not found" in text:
        return "dependency"
    if "skipped_by_threshold" in text or "all_skipped" in text or "metrics_threshold" in text:
        return "skipped_threshold"
    return "unexpected"


def resolve_adapter_run_mode(run_mode: str | None = None) -> str:
    candidate = str(run_mode or os.getenv("QUANT WORKER_RUN_MODE", "")).strip().lower()
    if candidate == RUN_MODE_RESEARCH:
        return RUN_MODE_RESEARCH
    return RUN_MODE_FULL


def build_runtime_state(
    failure_kind: str,
    error_text: str,
    exit_code: int,
    last_leaf_job: str,
) -> dict[str, object]:
    timestamp = now_utc()
    adapter_status = "DEGRADED" if failure_kind else "RUNNING"
    return {
        "adapter_status": adapter_status,
        "failure_kind": failure_kind or "none",
        "last_error": error_text,
        "last_exit_code": exit_code,
        "last_leaf_job": last_leaf_job,
        "updated_at": timestamp,
        "heartbeat_at": timestamp,
    }


def assess_chain_coverage(project_state: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    mode = str(project_state.get("mode", "") or "")
    submit_enabled = bool(project_state.get("submit_enabled", False))
    # Full pipeline: evolve → candidate_gen → candidate_sub → submit_batch
    active_capabilities = [
        "evolve_skill_preview",
        "candidate_generate",
        "candidate_submit",
        "submit_batch",
    ]
    missing_capabilities: list[str] = []

    if not (submit_enabled or mode == "research+submit"):
        # Without submit mode, remove submit stages
        active_capabilities.remove("submit_batch")
        active_capabilities.remove("candidate_submit")
        missing_capabilities.extend(["submit_batch", "candidate_submit"])
        coverage_status = "partial"
    else:
        coverage_status = "full"

    return coverage_status, active_capabilities, missing_capabilities


def _build_business_impact(
    workflow_verdicts: dict[str, dict[str, str]],
    project_state: dict[str, Any],
) -> list[str]:
    """Build dynamic business impact summary from actual state.

    No hardcoded messages — reflects what the system IS doing right now.
    """
    impacts: list[str] = []
    last_leaf = str(project_state.get("last_leaf_job", ""))
    cycle = int(project_state.get("cycle_count", 0))
    leaf_map = {
        "evolve_skill_preview": "研究快照扫描",
        "candidate_generate": "新因子候选生成",
        "candidate_submit": "候选因子仿真与提交",
        "submit_batch": "固定模板批量提交",
    }
    current_phase = leaf_map.get(last_leaf, last_leaf or "未知")

    research = workflow_verdicts.get("research_chain", {})
    submit = workflow_verdicts.get("submit_chain", {})
    production = workflow_verdicts.get("production_chain", {})
    truth = workflow_verdicts.get("truth_closure_chain", {})

    impacts.append(f"当前阶段: {current_phase} (第 {cycle} 轮)")
    impacts.append(f"研究链: {research.get('state', 'unknown')} | 提交链: {submit.get('state', 'unknown')}")
    impacts.append(f"生产链: {production.get('state', 'unknown')} | 真相闭环: {truth.get('state', 'unknown')}")
    return impacts


def build_authority_map() -> dict[str, str]:
    return {
        "project_runtime_state": classify_state_source("project_runtime_state"),
        "batch_submit_results": classify_state_source("batch_submit_results"),
        "project_runtime_log": classify_state_source("project_runtime_log"),
        "adapter_state": classify_state_source("adapter_state"),
        "panel_state": classify_state_source("panel_state"),
    }


def load_credentials() -> tuple[str, str]:
    user = os.getenv("WQ_BRAIN_USERNAME")
    password = os.getenv("WQ_BRAIN_PASSWORD")
    if user and password:
        return user, password
    credential_path = PROJECT_ROOT / "credential.txt"
    if credential_path.exists():
        user, password = json.loads(credential_path.read_text(encoding="utf-8"))
        return str(user), str(password)
    raise FileNotFoundError("缺少 BRAIN 凭据，请先配置 WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD")


def read_project_state() -> dict[str, Any]:
    if not PROJECT_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(PROJECT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "STATE_ERROR", "last_error": str(exc)}
    return payload if isinstance(payload, dict) else {}


def bootstrap_runtime_state(previous_state: dict[str, Any]) -> dict[str, Any]:
    previous_updated_at = str(previous_state.get("updated_at", "") or "")
    deadline = time.time() + BOOTSTRAP_WAIT_SECONDS
    latest_state = previous_state
    while time.time() <= deadline:
        current_state = read_project_state()
        current_updated_at = str(current_state.get("updated_at", "") or "")
        if current_state and current_updated_at and current_updated_at != previous_updated_at:
            return current_state
        if current_state:
            latest_state = current_state
        time.sleep(0.1)
    return latest_state


def persist_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ADAPTER_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_supervised_state(
    project_state: dict[str, Any],
    *,
    last_error: str = "",
    submit_results: list[dict[str, Any]] | None = None,
    submit_results_updated_at: str | None = None,
    alpha_db_present: bool | None = None,
) -> dict[str, Any]:
    project_error = str(project_state.get("last_error", "") or "")
    effective_error = last_error or project_error
    failure_kind = classify_failure(effective_error) if effective_error else ""
    state = build_runtime_state(
        failure_kind,
        effective_error,
        int(project_state.get("last_exit_code", 0) or 0),
        str(project_state.get("last_leaf_job", "") or ""),
    )
    coverage_status, active_capabilities, missing_capabilities = assess_chain_coverage(project_state)
    submit_results_path = PROJECT_ROOT / "batch_submit_results.json"
    submit_results_payload = load_submit_results_payload(submit_results_path) if submit_results is None else submit_results
    if submit_results_updated_at is None and submit_results_path.exists():
        submit_results_updated_at = datetime.fromtimestamp(submit_results_path.stat().st_mtime, timezone.utc).isoformat()
    submit_results_fresh = submit_results_are_fresh_for_runtime(
        submit_results_updated_at=str(submit_results_updated_at or ""),
        runtime_updated_at=str(project_state.get("updated_at", "") or ""),
    )
    alpha_db_exists = (PROJECT_ROOT / "alpha_db.json").exists() if alpha_db_present is None else alpha_db_present
    workflow_verdicts = audit_workflows(
        project_state=project_state,
        submit_results=submit_results_payload,
        submit_results_fresh=submit_results_fresh,
        alpha_db_present=alpha_db_exists,
    )
    state["coverage_status"] = coverage_status
    state["active_capabilities"] = active_capabilities
    state["missing_capabilities"] = missing_capabilities
    state["authority_map"] = build_authority_map()
    state["workflow_verdicts"] = workflow_verdicts
    state["business_impact"] = _build_business_impact(workflow_verdicts, project_state)
    state["next_attention"] = workflow_verdicts["production_chain"]["root_cause"]
    state["project_state"] = project_state
    return state


def run_project_runtime(*, run_mode: str | None = None) -> subprocess.Popen[str]:
    load_credentials()
    canonical_run_mode = resolve_adapter_run_mode(run_mode)
    env = os.environ.copy()
    env["QUANT WORKER_RUN_MODE"] = canonical_run_mode
    env["QUANT WORKER_RUNTIME_ENABLE_SUBMIT"] = "1" if canonical_run_mode == RUN_MODE_FULL else "0"
    return subprocess.Popen(
        [sys.executable, str(PROJECT_RUNTIME)],
        cwd=str(PROJECT_ROOT),
        text=True,
        env=env,
    )


def ensure_single_instance() -> SingleInstanceGuard:
    guard = SingleInstanceGuard(ADAPTER_LOCK_PATH)
    guard.acquire(active_pids=list_active_python_pids())
    return guard


def sleep_forever() -> None:
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        project_state = read_project_state()
        persist_state(build_supervised_state(project_state))


def main() -> int:
    """Start the adapter host.

    Two modes:
      standalone (no args): adapter spawns AND monitors project_runtime.
      supervised (--supervised): adapter only monitors. ProcessManager
        starts project_runtime separately.
    """
    import sys as _sys
    supervised = "--supervised" in _sys.argv

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    guard = ensure_single_instance()

    process = None
    if not supervised:
        previous_project_state = read_project_state()
        process = run_project_runtime(run_mode=resolve_adapter_run_mode())
        initial_project_state = bootstrap_runtime_state(previous_project_state)
        persist_state(build_supervised_state(initial_project_state))
    else:
        # In supervised mode, just write an initial state showing we're alive
        persist_state(build_supervised_state(read_project_state()))

    rc = None
    try:
        while True:
            project_state = read_project_state()
            persist_state(build_supervised_state(project_state))
            if process is not None:
                rc = process.poll()
                if rc is not None:
                    last_error = str(project_state.get("last_error", "") or "")
                    if rc != 0 and not last_error:
                        last_error = f"project_runtime exited with code {rc}"
                    final_state = build_supervised_state(project_state, last_error=last_error)
                    final_state["last_exit_code"] = rc
                    persist_state(final_state)
                    break
            time.sleep(HEARTBEAT_SECONDS)
    finally:
        if process is not None and rc is None and process.poll() is None:
            process.terminate()
        guard.release()
    return int(rc or 0)


if __name__ == "__main__":
    raise SystemExit(main())
