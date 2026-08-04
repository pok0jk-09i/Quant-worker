"""Quant worker start script — supervised process tree.

Usage:
    python start.py                # start all services
    python start.py --no-submit    # research only (skip submit chain)

Replaces the old launch_stack with production-grade supervision:
  - Auto-restart with exponential backoff
  - Zombie process cleanup on exit
  - Circuit breaker trips on repeated failures
  - Signal handling (Ctrl+C for graceful shutdown)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the quant_worker_monitor_panel package is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_worker_monitor_panel.supervisor import (  # noqa: E402
    ProcessManager,
    SupervisedProcess,
    assert_environment,
    make_heartbeat_dir,
)

# ── Script paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT
WQ_ALPHA_ROOT = Path(os.getenv("QUANT WORKER_RESEARCH_ROOT", r"E:\Quant worker-CLEAN\wq-alpha-research"))

PROJECT_RUNTIME_SCRIPT = WQ_ALPHA_ROOT / "project_runtime.py"
ADAPTER_SCRIPT = SCRIPTS_DIR / "adapter_host.py"
PANEL_SCRIPT = SCRIPTS_DIR / "panel_app.py"

# The interpreter known to have requests + numpy installed. We PIN it so a
# launcher using the wrong Python cannot poison every child process. If
# start.py is itself launched with the wrong interpreter, assert_environment
# below fails fast (exit 78) with a clear message instead of a silent death.
PINNED_PYTHON = os.getenv("QUANT WORKER_PYTHON", r"E:\Python311\python.exe")


def main() -> int:
    # 1) Fail fast on a wrong/missing environment — the #1 cause of outages.
    try:
        assert_environment(PINNED_PYTHON)
    except SystemExit as exc:
        # Re-raised by assert_runtime_contract; surface and exit.
        return int(getattr(exc, "code", 1) or 1)

    run_mode = os.getenv("QUANT WORKER_RUN_MODE", "research+submit").strip() or "research+submit"
    no_submit = "--no-submit" in sys.argv

    if no_submit:
        run_mode = "research"
        os.environ["QUANT WORKER_RUN_MODE"] = "research"

    # Validate scripts exist
    missing = []
    for label, path in [
        ("项目运行时", PROJECT_RUNTIME_SCRIPT),
        ("适配器", ADAPTER_SCRIPT),
        ("监控面板", PANEL_SCRIPT),
    ]:
        if not path.exists():
            missing.append(f"{label}: {path}")

    if missing:
        for m in missing:
            print(f"[错误] 缺失: {m}")
        return 1

    hb_dir = make_heartbeat_dir()
    # Build supervision tree with the PINNED interpreter + liveness heartbeats.
    manager = ProcessManager(executable=PINNED_PYTHON, heartbeat_dir=hb_dir)

    # ── Adapter (auxiliary, non-critical) ──
    manager.add(SupervisedProcess(
        label="适配器主机",
        script=ADAPTER_SCRIPT,
        cwd=ADAPTER_SCRIPT.parent,
        args=["--supervised"],
        env={"QUANT WORKER_RUN_MODE": run_mode},
        is_critical=False,
        max_restarts=5,
    ))

    # ── Project Runtime (critical) ── emits a heartbeat the supervisor watches.
    manager.add(SupervisedProcess(
        label="项目运行时",
        script=PROJECT_RUNTIME_SCRIPT,
        cwd=PROJECT_RUNTIME_SCRIPT.parent,
        env={"QUANT WORKER_RUN_MODE": run_mode, "QUANT WORKER_PYTHON": PINNED_PYTHON},
        is_critical=True,
        max_restarts=10,
        heartbeat_path=hb_dir / "hb_project_runtime.json",
    ))

    # ── Panel (critical — the monitoring dashboard) ──
    manager.add(SupervisedProcess(
        label="监控面板",
        script=PANEL_SCRIPT,
        cwd=PANEL_SCRIPT.parent,
        env={},
        is_critical=True,
        max_restarts=10,
    ))

    print(f"[start] Quant worker 启动 (run_mode={run_mode}, python={PINNED_PYTHON})")
    print(f"[start] 按 Ctrl+C 优雅关闭")

    manager.start_all()
    manager.monitor()

    print("[start] 系统已关闭")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
