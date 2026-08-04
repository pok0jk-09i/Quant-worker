# Quant worker Supervisor Control Plane Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the external Quant worker monitor workspace into a truthful supervisor control plane that reports real workflow closure, chain health, and business impact without modifying the upstream Quant worker project repository.

**Architecture:** Keep `E:\Quant worker-CLEAN\wq-alpha-research` untouched and move all structural repair into `E:\Quant worker-monitor-web-panel`. The monitor workspace becomes a control plane composed of a runtime truth reader, a chain auditor, a supervisor state builder, and a rewritten panel contract. The control plane reads authoritative project artifacts, derives workflow verdicts, and exposes chain-level truth instead of optimistic whole-system summaries.

**Tech Stack:** Python 3.11, `json`, `pathlib`, `subprocess`, `threading`, local JSON state files, Windows launcher, `pytest`.

---

## 1. Problem Statement

The current external monitor stack correctly launches and observes the Quant worker runtime, but it still compresses several distinct workflow states into coarse summaries such as `coverage_status=full`. That behavior is structurally misleading because the upstream project currently closes:

- a research snapshot chain,
- a fixed-template submit governance chain,
- and a monitor display chain,

but it does **not** close a true new-factor production chain.

The supervisor layer must stop acting like a presentation wrapper and become an explicit control plane that distinguishes:

- authoritative truth,
- derived supervisory interpretation,
- display-only projection.

## 2. Repair Boundaries

### In Scope

- `E:\Quant worker-monitor-web-panel\adapter_host.py`
- `E:\Quant worker-monitor-web-panel\panel_app.py`
- `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\core.py`
- `E:\Quant worker-monitor-web-panel\quant_worker_monitor_panel\launch_stack.py`
- new monitor-side helper modules and tests
- monitor-side spec, plan, and verification artifacts

### Out of Scope

- any modification under `E:\Quant worker-CLEAN\wq-alpha-research`
- changing `project_runtime.py` run order
- changing `evolve_skill.py` from preview to apply mode
- adding new-factor generation logic to the upstream project
- rewriting upstream submit behavior

## 3. Design Principles

1. The monitor workspace is the **control plane**, not the business data plane.
2. The control plane must never claim capabilities the upstream project does not actually expose.
3. All health summaries must be chain-level, not process-level.
4. Every panel conclusion must be traceable to file-backed evidence.
5. Authority, derived, and display-only states must be explicitly separated.

## 4. Source-of-Truth Model

The control plane must classify state sources with fixed semantics:

### Authority

- `%LOCALAPPDATA%\Quant worker-Monitor\project_runtime_state.json`
- `E:\Quant worker-CLEAN\wq-alpha-research\batch_submit_results.json`
- `%LOCALAPPDATA%\Quant worker-Monitor\project_runtime.log`

### Derived

- `%LOCALAPPDATA%\Quant worker-Monitor\adapter_state.json`

### Display Only

- `%LOCALAPPDATA%\Quant worker-Monitor\panel_state.json`

The adapter layer must never elevate derived or display-only files into authoritative truth.

## 5. Workflow Model

The supervisor must evaluate four workflow chains independently.

### 5.1 Research Chain

Definition:
- the runtime is currently executing upstream research snapshot behavior

Primary evidence:
- `project_runtime_state.last_leaf_job == "evolve_skill_preview"`
- `project_runtime_state.last_progress` indicates snapshot stages such as `fetch_alphas`, `fetch_pnl`, or `incremental_scan`

Expected states:
- `complete`
- `partial`
- `pseudo`
- `broken`
- `unknown`

Interpretation rule:
- preview mode without durable `alpha_db.json` writeback cannot be reported as a fully closed research memory loop

### 5.2 Submit Chain

Definition:
- the runtime is capable of executing the fixed-template submit workflow and summarizing its results

Primary evidence:
- runtime mode includes submit
- `batch_submit_results.json` exists or runtime state contains `submission_summary`
- submit governance fields are present in runtime state

### 5.3 Production Chain

Definition:
- a new-factor production workflow that generates fresh candidates and routes them into submitable consumption

Primary evidence required for `complete`:
- a durable candidate source
- a runtime-consumed candidate bridge
- evidence that submit consumes generated candidates rather than only fixed templates

Current expected result:
- `broken`

### 5.4 Truth Closure Chain

Definition:
- whether each running workflow closes its own durable truth loop

Examples:
- submit chain may close through `batch_submit_results.json -> submission_summary`
- research chain does not fully close when preview mode never writes `alpha_db.json`

## 6. Runtime Truth Reader

Create a dedicated monitor-side reader responsible only for reading and normalizing upstream facts. It must:

- read project runtime state safely
- read submit result payload safely
- read log tails safely
- return file-backed facts without policy decisions

It must not:

- classify chain health
- emit user-facing verdict text
- merge display preferences into runtime facts

## 7. Chain Auditor

Create a dedicated monitor-side auditor that converts runtime facts into workflow verdicts.

For each chain it must output:

- `state`
- `summary`
- `evidence`
- `impact`
- `root_cause`

Required business rules:

- running `evolve_skill_preview` with no durable writeback may be `partial` but not `complete`
- submit mode plus submit governance data may classify submit chain as `complete`
- lack of any runtime-consumed candidate bridge must classify production chain as `broken`
- truth closure must remain `partial` when any running workflow does not durably close its state loop

## 8. Supervisor State Contract

`adapter_state.json` must be upgraded from a thin process-state projection into a supervisor contract.

Required top-level fields:

- `supervisor_status`
- `authority_map`
- `workflow_verdicts`
- `business_impact`
- `next_attention`
- `last_leaf_job`
- `updated_at`
- `heartbeat_at`
- `project_state`

The old `coverage_status=full|partial` field should be deprecated from decision-making. It may remain temporarily for compatibility, but panel decisions must not rely on it.

## 9. Panel Contract

The panel must stop compressing everything into generalized health wording.

The panel must instead render:

- current running workflow
- missing or broken workflows
- true business impact
- latest submit governance verdict
- truth-source map
- primary root cause blocking full production closure

Examples of acceptable statements:

- `当前运行链：研究快照链`
- `提交链：固定模板批量测试链可用`
- `新因子生产链：未接入`
- `研究真相闭环：未闭合，原因是 preview 模式未形成 durable writeback`

## 10. Launcher Contract

The launcher remains external and must continue to start:

- the supervisor host
- the panel

But launcher success must not be equated with business completion.

The supervisor must perform post-launch validation and persist chain verdicts before the panel claims healthy operation.

## 11. Testing Strategy

All implementation must follow monitor-side TDD only. Tests should cover:

- authority map classification
- research chain classification
- submit chain classification
- production chain broken-state detection
- truth closure partial-state detection
- panel rendering for chain verdicts
- launcher behavior remaining external-only

## 12. Success Criteria

This design is successful only if the monitor layer can truthfully say all of the following when appropriate:

- the runtime is running
- the submit chain is available
- the production chain is not connected
- the research chain is active but not durably closed
- the panel conclusion is derived from authority-backed evidence

If the panel still collapses those conditions into `full coverage`, the repair is incomplete.
