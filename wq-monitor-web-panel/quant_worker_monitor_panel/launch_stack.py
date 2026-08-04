from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from quant_worker_monitor_panel.single_instance import SingleInstanceGuard, list_active_python_pids


DEFAULT_PYTHON = Path(r"E:\Python311\python.exe")
DEFAULT_PROJECT_SCRIPT = Path(r"E:\Quant worker-CLEAN\wq-alpha-research\project_runtime.py")
DEFAULT_PANEL_SCRIPT = Path(r"E:\Quant worker-monitor-web-panel\panel_app.py")
DEFAULT_ADAPTER_SCRIPT = Path(r"E:\Quant worker-monitor-web-panel\adapter_host.py")

# Lock file location (shared with adapter_host and panel_app)
LOCK_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Quant worker-Monitor"
DEFAULT_ADAPTER_SCRIPT = Path(r"E:\Quant worker-monitor-web-panel\adapter_host.py")


@dataclass(frozen=True)
class LaunchTarget:
    label: str
    script: Path
    cwd: Path
    lock_name: str
    supervise: bool = True
    env_overrides: dict[str, str] | None = None


def build_launch_targets(
    python_executable: Path,
    project_script: Path = DEFAULT_PROJECT_SCRIPT,
    panel_script: Path = DEFAULT_PANEL_SCRIPT,
    adapter_script: Path = DEFAULT_ADAPTER_SCRIPT,
    run_mode: str = "research+submit",
) -> list[LaunchTarget]:
    return [
        LaunchTarget(
            label="适配器主机",
            script=adapter_script,
            cwd=adapter_script.parent,
            lock_name="quant_worker_adapter_host",
            supervise=True,
            env_overrides={"QUANT WORKER_RUN_MODE": run_mode},
        ),
        LaunchTarget(
            label="项目运行时",
            script=project_script,
            cwd=project_script.parent,
            lock_name="quant_worker_project_runtime",
            supervise=True,
            env_overrides={"QUANT WORKER_RUN_MODE": run_mode},
        ),
        LaunchTarget(
            label="监控面板",
            script=panel_script,
            cwd=panel_script.parent,
            lock_name="quant_worker_panel_app",
            supervise=True,
            env_overrides={},
        ),
    ]


def split_existing_and_missing(
    targets: Iterable[LaunchTarget],
) -> tuple[list[LaunchTarget], list[LaunchTarget]]:
    existing: list[LaunchTarget] = []
    missing: list[LaunchTarget] = []
    for target in targets:
        if target.script.exists():
            existing.append(target)
        else:
            missing.append(target)
    return existing, missing


def build_status_lines(existing: Iterable[LaunchTarget], missing: Iterable[LaunchTarget]) -> list[str]:
    lines: list[str] = []
    for target in existing:
        lines.append(f"[就绪] {target.label}: {target.script}")
    for target in missing:
        lines.append(f"[缺失] {target.label}: {target.script}")
    return lines


def launch_targets(
    python_executable: Path,
    targets: Iterable[LaunchTarget],
) -> list[subprocess.Popen[str]]:
    processes: list[subprocess.Popen[str]] = []
    guards: list[SingleInstanceGuard] = []
    active_pids = list_active_python_pids()
    for target in targets:
        # Per-target single-instance guard: refuse to launch if the
        # corresponding lock file is held by another LIVE process.
        lock_path = LOCK_DIR / f"{target.lock_name}.lock"
        guard = SingleInstanceGuard(lock_path)
        try:
            guard.acquire(active_pids=active_pids)
        except RuntimeError as exc:
            print(f"[skip] {target.label}: {exc}")
            continue
        guards.append(guard)

        env = os.environ.copy()
        env.update(target.env_overrides or {})
        process = subprocess.Popen(
            [str(python_executable), str(target.script)],
            cwd=str(target.cwd),
            text=True,
            env=env,
        )
        processes.append(process)
        # Update active_pids so the next target sees this new process as live.
        active_pids.add(process.pid)
    return processes


def launch_and_wait(targets: list[LaunchTarget]) -> int:
    python_executable = DEFAULT_PYTHON if DEFAULT_PYTHON.exists() else Path(sys.executable)
    processes = launch_targets(python_executable, targets)
    if not processes:
        return 1

    # Wait for the last process (usually panel) to exit
    last_process = processes[-1]
    try:
        return last_process.wait()
    finally:
        # Terminate all other processes
        for process in processes[:-1]:
            if process.poll() is None:
                process.terminate()


def main() -> int:
    python_executable = DEFAULT_PYTHON if DEFAULT_PYTHON.exists() else Path(sys.executable)
    run_mode = str(os.getenv("QUANT WORKER_RUN_MODE", "research+submit")).strip() or "research+submit"
    targets = build_launch_targets(
        python_executable,
        DEFAULT_PROJECT_SCRIPT,
        DEFAULT_PANEL_SCRIPT,
        DEFAULT_ADAPTER_SCRIPT,
        run_mode=run_mode,
    )
    existing, missing = split_existing_and_missing(targets)
    if missing:
        for line in build_status_lines(existing, missing):
            print(line)
        print("启动已拒绝：所有目标必须同时完整存在。")
        return 2

    return launch_and_wait(existing)


if __name__ == "__main__":
    raise SystemExit(main())
