# Quant worker External Adapter Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a zero-intrusion external adapter layer that keeps the Quant worker project runnable and observable even when the upstream project scripts hit API contract mismatches, without modifying the project repository itself.

**Architecture:** The desktop launcher starts an external adapter host and the monitor panel. The adapter host owns credentials loading, leaf-script invocation, error classification, retries, and external state emission. The monitor panel reads only external state files and never infers project truth from raw leaf outputs.

**Tech Stack:** Python 3.11, `subprocess`, `socket`, `json`, `threading`, local JSON state files, Windows batch launcher, `pytest`.

---

### Task 1: Define the adapter-host contract

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

Create `classify_failure()` and `choose_leaf_mode()` only.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\tests\test_adapter_host.py
git commit -m "feat: add external adapter host contract"
```

### Task 2: Route launcher through the adapter host

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py`

- [ ] **Step 1: Write the failing test**

```python
def test_launcher_targets_adapter_host_instead_of_leaf_script():
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py -v
```
Expected: FAIL until the launcher points at the adapter host.

- [ ] **Step 3: Write minimal implementation**

Replace the direct project script target with `adapter_host.py`; keep the panel target unchanged; preserve no-partial-start behavior.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py
git commit -m "feat: launch adapter host instead of project leaf"
```

### Task 3: Expose adapter state to the panel

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

Add a panel-facing summary renderer for adapter state and display it alongside project runtime state.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py
git commit -m "feat: show adapter state in monitor panel"
```

### Task 4: Make the adapter host resilient

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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_adapter_runtime.py -v
```
Expected: FAIL until runtime state builder exists.

- [ ] **Step 3: Write minimal implementation**

Implement runtime-state emission, retry classification, and leaf supervision.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\tests\test_adapter_runtime.py
git commit -m "feat: make adapter host resilient"
```

### Task 5: End-to-end verification

**Files:**
- Verify only: `C:\Users\USERNAME\Desktop\Quant worker 启动器.bat`
- Verify only: `E:\Quant worker-monitor-web-panel\adapter_host.py`
- Verify only: `E:\Quant worker-monitor-web-panel\panel_app.py`

- [ ] **Step 1: Run the desktop launcher**

Confirm the adapter host and panel both start.

- [ ] **Step 2: Verify live state**

Check that the external state file exists, that `failure_kind` is exposed when the leaf fails, and that the panel renders the adapter summary.

- [ ] **Step 3: Verify project repo remains untouched**

Confirm no file under `E:\Quant worker-CLEAN\wq-alpha-research` was modified.

- [ ] **Step 4: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py
git commit -m "chore: externalize Quant worker adapter layer"
```

## Self-Review

- The design keeps the project repository untouched.
- Error classification is explicit and externally visible.
- Panel rendering depends only on adapter state, not on raw leaf outputs.
- The plan is narrow enough to implement and verify independently.
