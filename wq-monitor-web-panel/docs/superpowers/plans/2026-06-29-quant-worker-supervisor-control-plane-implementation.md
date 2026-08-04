# Quant worker Supervisor Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a monitor-side supervisor control plane that truthfully models Quant worker workflow closure and chain health without changing the upstream Quant worker project repository.

**Architecture:** Keep the upstream project untouched and upgrade only `E:\Quant worker-monitor-web-panel`. Add a runtime truth reader and chain auditor, rebuild the adapter state contract around supervisor verdicts, and rewrite the panel to render chain-level truth sourced from authority-backed evidence.

**Tech Stack:** Python 3.11, `json`, `pathlib`, `subprocess`, `threading`, local JSON state files, Windows launcher, `pytest`.

---

### Task 1: Introduce a runtime truth reader module

**Files:**
- Create: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\runtime_truth.py`
- Create: `E:\Quant worker-monitor-web-panel\tests\test_runtime_truth.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from quant_worker_monitor_panel.runtime_truth import classify_state_source, load_submit_results_payload


def test_classify_state_source_distinguishes_authority_and_display_only():
    assert classify_state_source("project_runtime_state") == "authority"
    assert classify_state_source("batch_submit_results") == "authority"
    assert classify_state_source("adapter_state") == "derived"
    assert classify_state_source("panel_state") == "display_only"


def test_load_submit_results_payload_returns_empty_list_for_missing_file(tmp_path: Path):
    payload = load_submit_results_payload(tmp_path / "missing.json")
    assert payload == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_runtime_truth.py -v
```
Expected: FAIL because `runtime_truth.py` does not yet exist.

- [ ] **Step 3: Write minimal implementation**

Implement `runtime_truth.py` with:
- `classify_state_source(name: str) -> str`
- `load_json_dict(path: Path) -> dict`
- `load_submit_results_payload(path: Path) -> list[dict]`
- optional log-tail helper kept read-only

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\runtime_truth.py E:\Quant worker-monitor-web-panel\tests\test_runtime_truth.py
git commit -m "feat: add runtime truth reader"
```

### Task 2: Add a chain auditor with chain-level verdicts

**Files:**
- Create: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\chain_auditor.py`
- Create: `E:\Quant worker-monitor-web-panel\tests\test_chain_auditor.py`

- [ ] **Step 1: Write the failing test**

```python
from quant_worker_monitor_panel.chain_auditor import audit_workflows


def test_audit_workflows_marks_production_chain_as_broken_when_only_preview_and_fixed_submit_exist():
    result = audit_workflows(
        project_state={
            "mode": "research+submit",
            "submit_enabled": True,
            "last_leaf_job": "evolve_skill_preview",
            "last_progress": "stage: fetch_pnl | 4803/10000",
        },
        submit_results=[{"submission": {"submitted": False, "reason": "metrics_threshold"}}],
        alpha_db_present=False,
    )
    assert result["production_chain"]["state"] == "broken"


def test_audit_workflows_marks_research_chain_as_partial_without_durable_writeback():
    result = audit_workflows(
        project_state={
            "last_leaf_job": "evolve_skill_preview",
            "last_progress": "stage: fetch_pnl | 10/100",
        },
        submit_results=[],
        alpha_db_present=False,
    )
    assert result["research_chain"]["state"] == "partial"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_chain_auditor.py -v
```
Expected: FAIL because `chain_auditor.py` does not yet exist.

- [ ] **Step 3: Write minimal implementation**

Implement:
- `audit_workflows(...) -> dict`
- verdict builders for:
  - `research_chain`
  - `submit_chain`
  - `production_chain`
  - `truth_closure_chain`

Each verdict must contain:
- `state`
- `summary`
- `impact`
- `root_cause`

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\chain_auditor.py E:\Quant worker-monitor-web-panel\tests\test_chain_auditor.py
git commit -m "feat: add chain auditor"
```

### Task 3: Rebuild adapter host as a supervisor state builder

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\adapter_host.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_adapter_host_state.py`

- [ ] **Step 1: Write the failing test**

```python
from adapter_host import build_supervised_state


def test_build_supervised_state_emits_workflow_verdicts_and_authority_map():
    state = build_supervised_state(
        {
            "mode": "research+submit",
            "submit_enabled": True,
            "last_leaf_job": "evolve_skill_preview",
            "last_progress": "stage: fetch_pnl | 10/100",
        },
        submit_results=[{"submission": {"submitted": False, "reason": "metrics_threshold"}}],
        alpha_db_present=False,
    )
    assert state["authority_map"]["project_runtime_state"] == "authority"
    assert state["workflow_verdicts"]["production_chain"]["state"] == "broken"
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_adapter_host_state.py -v
```
Expected: FAIL because the current supervised state does not expose the new contract.

- [ ] **Step 3: Write minimal implementation**

Update `adapter_host.py` to:
- read runtime facts through `runtime_truth.py`
- compute verdicts through `chain_auditor.py`
- emit:
  - `supervisor_status`
  - `authority_map`
  - `workflow_verdicts`
  - `business_impact`
  - `next_attention`

Retain compatibility fields only if needed by legacy tests, but make new panel behavior depend on the new supervisor contract.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\tests\test_adapter_host_state.py
git commit -m "feat: upgrade adapter host to supervisor state builder"
```

### Task 4: Rewrite panel summaries around chain truth

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py`
- Modify: `E:\Quant worker-monitor-web-panel\panel_app.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_core.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py`

- [ ] **Step 1: Write the failing test**

```python
from quant_worker_monitor_panel.core import build_adapter_summary_lines


def test_build_adapter_summary_lines_renders_chain_level_truth():
    lines = build_adapter_summary_lines(
        {
            "workflow_verdicts": {
                "research_chain": {"state": "partial", "summary": "研究快照工作流运行中"},
                "submit_chain": {"state": "complete", "summary": "固定模板提交治理链可用"},
                "production_chain": {"state": "broken", "summary": "新因子生产链未接入"},
                "truth_closure_chain": {"state": "partial", "summary": "研究记忆真相未闭合"},
            }
        }
    )
    assert any("新因子生产链未接入" in line for line in lines)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_core.py E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py -v
```
Expected: FAIL because the current panel summary path still reflects coarse adapter summaries.

- [ ] **Step 3: Write minimal implementation**

Update the panel rendering contract to display:
- current running chain
- missing or broken chains
- business impact
- truth source map
- latest submit governance truth if present

Avoid vague whole-system summaries when chain-level truth is available.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\tests\test_core.py E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py
git commit -m "feat: render supervisor chain truth in panel"
```

### Task 5: Tighten launcher validation around supervisor startup

**Files:**
- Modify: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py`
- Modify: `E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from quant_worker_monitor_panel.launch_stack import build_launch_targets


def test_build_launch_targets_still_launches_supervisor_then_panel():
    targets = build_launch_targets(
        Path("E:/Python311/python.exe"),
        Path("E:/Quant worker-monitor-web-panel/adapter_host.py"),
        Path("E:/Quant worker-monitor-web-panel/panel_app.py"),
        run_mode="research+submit",
    )
    assert [target.script.name for target in targets] == ["adapter_host.py", "panel_app.py"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py -v
```
Expected: FAIL only if launch behavior regresses while adding supervisor validation.

- [ ] **Step 3: Write minimal implementation**

Preserve existing external-only launch behavior and add only the minimum wiring needed so supervisor startup remains the canonical project-side entrypoint for the monitor workspace.

- [ ] **Step 4: Run test to verify it passes**

Run the same pytest command.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py
git commit -m "chore: preserve launcher discipline for supervisor control plane"
```

### Task 6: Full monitor-side verification

**Files:**
- Verify only: `E:\Quant worker-monitor-web-panel\adapter_host.py`
- Verify only: `E:\Quant worker-monitor-web-panel\panel_app.py`
- Verify only: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\runtime_truth.py`
- Verify only: `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\chain_auditor.py`

- [ ] **Step 1: Run focused tests**

Run:
```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; pytest E:\Quant worker-monitor-web-panel\tests\test_runtime_truth.py E:\Quant worker-monitor-web-panel\tests\test_chain_auditor.py E:\Quant worker-monitor-web-panel\tests\test_adapter_host_state.py E:\Quant worker-monitor-web-panel\tests\test_core.py E:\Quant worker-monitor-web-panel\tests\test_adapter_state_panel.py E:\Quant worker-monitor-web-panel\tests\test_launch_stack.py -v
```
Expected: PASS.

- [ ] **Step 2: Run live launcher validation**

Start the monitor stack and verify:
- `adapter_state.json` includes `authority_map`
- `workflow_verdicts.production_chain.state == "broken"` for the current upstream state
- panel text shows chain-level truth instead of a fake whole-system full coverage summary

- [ ] **Step 3: Verify upstream repo remains untouched**

Confirm no file changed under `E:\Quant worker-CLEAN\wq-alpha-research`.

- [ ] **Step 4: Commit**

```bash
git add E:\Quant worker-monitor-web-panel\adapter_host.py E:\Quant worker-monitor-web-panel\panel_app.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\runtime_truth.py E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\chain_auditor.py
git commit -m "feat: add Quant worker supervisor control plane"
```

## Self-Review

- The plan changes only the monitor workspace.
- The plan upgrades semantics, not just labels.
- The plan introduces explicit authority and chain verdict models.
- The plan remains implementable with monitor-side TDD and without upstream edits.
