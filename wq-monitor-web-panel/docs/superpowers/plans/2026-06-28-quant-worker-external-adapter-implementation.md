# Quant worker External Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a zero-intrusion external adapter layer for Quant worker that classifies leaf-script failures, keeps the desktop launcher stable, and exposes truthful adapter state in the monitor panel without changing the project repository.

**Architecture:** Add an external `adapter_host.py` in the monitor workspace that owns credentials, leaf execution, failure classification, retry policy, and adapter state emission. Update the existing launcher to start the adapter host instead of the raw project leaf. Extend the panel to read adapter state and display it alongside the existing project runtime state, while keeping the project repo untouched.

**Tech Stack:** Python 3.11, `subprocess`, `socket`, `json`, `threading`, `requests`, local JSON state files, Windows batch launcher, `pytest`.

---

### Task 1: Define the adapter host contract

**Files:**
- Create: `E:\Quant worker-monitor-web-panel\adapter_host.py`
- Create: `E:\Quant worker-monitor-web-panel\tests\test_adapter_host.py`

- [ ] **Step 1: Write the failing test**

```python
from adapter_host import classify_failure, choose_leaf_mode


def test_classify_failure_marks_invalid_offset_as_contract_mismatch():
    kind = classify_failure("RuntimeError: Failed to fetch alphas: 400 [\"Invalid offset. Please use filters to narrow down the result.\"]")
    assert kind == "contract_mismatch"


def test_choose_leaf_mode_defaults_to_research_only():
    mode = choose_leaf_mode(enable_submit=False)
    assert mode == ["evolve_skill_preview"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_adapter_host.py -v
```
Expected: FAIL because `adapter_host.py` does not yet exist.

- [ ] **Step 3: Write minimal implementation**

Implement `classify_failure()` and `choose_leaf_mode()` only. Keep the contract narrow:
- `classify_failure()` must return `contract_mismatch` for the current `Invalid offset` error text, `auth` for credential/auth failures, `network` for timeouts/connection failures, `dependency` for missing files/imports, and `unexpected` otherwise.
- `choose_leaf_mode()` must return the leaf list to run based on the submit flag without touching the project repo.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\tests\test_adapter_host.py
git commit -m "feat: add external adapter host contract"
```

### Task 2: Make the adapter host runnable and stateful

**Files:**
- Create: `E:\Quant worker-monitor-web-panel\tests\test_adapter_runtime.py`
- Modify: `E:\Quant worker-monitor-web-panel\adapter_host.py`

- [ ] **Step 1: Write the failing test**

```python
from adapter_host import build_runtime_state


def test_runtime_state_marks_contract_mismatch_as_degraded():
    state = build_runtime_state("contract_mismatch", "Invalid offset", 1, "evolve_skill_preview")
    assert state["adapter_status"] == "DEGRADED"
    assert state["failure_kind"] == "contract_mismatch"
    assert state["last_leaf_job"] == "evolve_skill_preview"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_adapter_runtime.py -v
```
Expected: FAIL because the runtime-state builder does not yet exist.

- [ ] **Step 3: Write minimal implementation**

Implement the runtime-state builder, leaf invocation wrapper, and state persistence in `adapter_host.py`:
- read credentials from the same local `credential.txt` / env var contract the current tools already use
- call leaf scripts via `subprocess`
- capture `stdout`, `stderr`, exit code, and heartbeat
- emit `adapter_state.json` in `%LOCALAPPDATA%\Quant worker-Monitor`

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\tests\test_adapter_runtime.py
git commit -m "feat: make adapter host stateful"
```

### Task 3: Route the launcher through the adapter host

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from quant_worker_monitor_panel.launch_stack import build_launch_targets


def test_launcher_targets_adapter_host_instead_of_leaf_script():
    targets = build_launch_targets(
        Path("E:/Python311/python.exe"),
        Path("E:/Quant worker-monitor-web-panel/adapter_host.py"),
        Path("E:/Quant worker-monitor-web-panel/panel_app.py"),
    )
    assert targets[0].script.name == "adapter_host.py"
    assert targets[1].script.name == "panel_app.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py -v
```
Expected: FAIL until the launcher points at the adapter host.

- [ ] **Step 3: Write minimal implementation**

Update the launcher so the project-side target becomes `adapter_host.py` instead of a raw project leaf script. Preserve:
- no partial start
- project and panel must both exist
- Windows-friendly process launch

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py
git commit -m "feat: launch adapter host instead of project leaf"
```

### Task 4: Expose adapter state in the panel

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\panel_app.py`
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py`
- Create: `E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py`

- [ ] **Step 1: Write the failing test**

```python
from quant_worker_monitor_panel.core import build_adapter_summary_lines


def test_adapter_summary_reports_contract_mismatch():
    lines = build_adapter_summary_lines(
        {
            "adapter_status": "DEGRADED",
            "failure_kind": "contract_mismatch",
            "last_error": "Invalid offset",
        }
    )
    assert any("contract_mismatch" in line for line in lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py -v
```
Expected: FAIL because the adapter summary helper does not yet exist.

- [ ] **Step 3: Write minimal implementation**

Add a panel-facing adapter summary helper in `core.py` and render it in `panel_app.py` alongside the project runtime summary. Keep the render path read-only and file-backed.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py
git commit -m "feat: show adapter state in monitor panel"
```

### Task 5: End-to-end verification

**Files:**
- Verify only: `C:\Users\USERNAME\Desktop\Quant worker 启动器.bat`
- Verify only: `E:\Quant worker-monitor-web-panel\adapter_host.py`
- Verify only: `E:\Quant worker-monitor-web-panel\panel_app.py`

- [ ] **Step 1: Run the desktop launcher**

Confirm the adapter host and panel both start from the same desktop entrypoint.

- [ ] **Step 2: Verify live state**

Check that `adapter_state.json` exists, that `failure_kind` is exposed when the leaf fails, and that the panel renders the adapter summary.

- [ ] **Step 3: Verify project repo remains untouched**

Confirm no file under `E:\Quant worker-CLEAN\wq-alpha-research` was modified.

- [ ] **Step 4: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py
git commit -m "chore: externalize Quant worker adapter layer"
```

## Self-Review

- The plan avoids all modifications to the Quant worker project repository.
- Failure classification is explicit and externally visible.
- Panel rendering depends only on adapter state, not raw leaf output.
- Every task is independently testable and keeps scope narrow.
