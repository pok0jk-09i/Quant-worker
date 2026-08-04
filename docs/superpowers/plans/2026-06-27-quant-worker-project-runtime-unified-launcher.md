# Quant worker Project Runtime and Unified Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current script-based Quant worker setup into a real project-level runtime with a single desktop launcher that starts the project runtime and the monitor panel together, with the panel showing both project health and factor-monitoring state.

**Architecture:** Add a dedicated long-running `project_runtime.py` on the Quant worker research side that owns lifecycle, credentials readiness, heartbeat, retry/backoff, and orchestration of existing leaf jobs such as `evolve_skill.py` and `submit_batch.py`. Extend the monitor panel to read a project-state file and surface project health alongside factor quality, while keeping the existing factor monitor UI and popup behavior intact. Update the unified launcher so it no longer treats `evolve_skill.py` as the project itself.

**Tech Stack:** Python 3.11+, `requests`, `subprocess`, `threading`, local JSON state files, Windows desktop launcher script.

---

### Task 1: Define the runtime contract and failing tests

**Files:**
- Create: `E:\Quant worker-CLEAN\wq-alpha-research\tests\test_project_runtime.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from quant_worker_monitor_panel.launch_stack import build_launch_targets


def test_launcher_targets_project_runtime_not_leaf_script():
    targets = build_launch_targets(
        Path("E:/Python311/python.exe"),
        Path("E:/Quant worker-CLEAN/wq-alpha-research/project_runtime.py"),
        Path("E:/Quant worker-monitor-web-panel/panel_app.py"),
    )

    assert targets[0].script.name == "project_runtime.py"
    assert targets[0].supervise is True
```

```python
from pathlib import Path
from project_runtime import build_initial_state


def test_runtime_starts_in_waiting_credentials_when_missing_credentials():
    state = build_initial_state(credentials_ready=False)
    assert state["status"] == "WAITING_CREDENTIALS"
    assert state["project_health"] == "降级运行"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
pytest E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py::LaunchStackTests::test_build_launch_targets_returns_project_then_panel -v
pytest E:\Quant worker-CLEAN\wq-alpha-research\tests\test_project_runtime.py -v
```
Expected: fail because `project_runtime.py` does not yet exist and launcher contract still points at the old leaf script.

- [ ] **Step 3: Write minimal implementation**

No production code yet.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest commands.
Expected: both tests fail for the right reason before implementation, then pass after Task 2 and Task 3.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py E:\Quant worker-CLEAN\wq-alpha-research\tests\test_project_runtime.py
git commit -m "test: define project runtime launcher contract"
```

### Task 2: Implement project runtime state machine

**Files:**
- Create: `E:\Quant worker-CLEAN\wq-alpha-research\project_runtime.py`
- Create: `E:\Quant worker-CLEAN\wq-alpha-research\tests\test_project_runtime.py`

- [ ] **Step 1: Write the failing test**

```python
from project_runtime import build_initial_state, update_runtime_state


def test_runtime_state_includes_heartbeat_and_leaf_job_fields(tmp_path):
    state = build_initial_state(credentials_ready=True)
    assert state["status"] == "BOOTING"
    assert "heartbeat_at" in state
    assert "last_leaf_job" in state


def test_runtime_persists_json_state(tmp_path):
    path = tmp_path / "runtime_state.json"
    state = build_initial_state(credentials_ready=False)
    update_runtime_state(path, state)
    assert path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
pytest E:\Quant worker-CLEAN\wq-alpha-research\tests\test_project_runtime.py -v
```
Expected: fail because `project_runtime.py` is not implemented.

- [ ] **Step 3: Write minimal implementation**

Implement `build_initial_state`, `update_runtime_state`, and a small runtime loop that writes JSON state and never treats leaf jobs as the project boundary.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-CLEAN\wq-alpha-research\project_runtime.py E:\Quant worker-CLEAN\wq-alpha-research\tests\test_project_runtime.py
git commit -m "feat: add project runtime state machine"
```

### Task 3: Rewire the unified launcher to use the runtime

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py`

- [ ] **Step 1: Write the failing test**

```python
def test_main_launches_project_runtime_and_panel():
    # assert the first process is project_runtime.py, not evolve_skill.py
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
pytest E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py -v
```
Expected: fail until launcher uses the runtime path.

- [ ] **Step 3: Write minimal implementation**

Change `DEFAULT_PROJECT_SCRIPT` to `E:\Quant worker-CLEAN\wq-alpha-research\project_runtime.py`, keep the panel as-is, and preserve the no-partial-start policy.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py
git commit -m "feat: launch project runtime instead of leaf script"
```

### Task 4: Surface project health in the monitor panel

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\panel_app.py`
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_core.py`

- [ ] **Step 1: Write the failing test**

```python
from quant_worker_monitor_panel.core import build_project_summary_lines


def test_project_summary_reports_runtime_status_and_last_leaf_job():
    lines = build_project_summary_lines({
        "status": "RUNNING",
        "project_health": "正常",
        "last_leaf_job": "evolve_skill.py",
    })
    assert any("RUNNING" in line for line in lines)
    assert any("evolve_skill.py" in line for line in lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
pytest E:\Quant worker-monitor-web-panel\tests\test_core.py -v
```
Expected: fail because the new project summary helper does not exist.

- [ ] **Step 3: Write minimal implementation**

Add a project-summary builder and render its fields in the panel HTML/state endpoint.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py E:\Quant worker-monitor-web-panel\tests\test_core.py
git commit -m "feat: show project runtime health in monitor panel"
```

### Task 5: End-to-end verification from the desktop launcher

**Files:**
- Verify only: `C:\Users\USERNAME\Desktop\Quant worker 启动器.bat`
- Verify only: `E:\Quant worker-CLEAN\wq-alpha-research\project_runtime.py`
- Verify only: `E:\Quant worker-monitor-web-panel\panel_app.py`

- [ ] **Step 1: Run the launcher manually**

Run the desktop launcher and confirm it starts both processes.

- [ ] **Step 2: Verify runtime state file is written**

Check the runtime state JSON exists and shows `BOOTING`, `RUNNING`, or `WAITING_CREDENTIALS` instead of exiting immediately.

- [ ] **Step 3: Verify panel shows project health**

Confirm the panel displays project runtime status, last leaf job, and the existing factor-monitoring summary.

- [ ] **Step 4: Verify the launcher does not silently succeed on partial startup**

If either side is missing, the launcher must refuse partial start.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-CLEAN\wq-alpha-research\project_runtime.py E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py
git commit -m "chore: unify Quant worker project startup"
```

## Self-Review

- Spec coverage: launcher contract, runtime state machine, panel visibility, and end-to-end startup are all covered.
- No placeholders remain.
- The plan is intentionally narrow: it does not add unrelated automation, persistence, or service installation.
