# Quant worker Core Production Gap Audit

**Goal:** Freeze the root-cause audit for why `E:\Quant worker-CLEAN\wq-alpha-research` does not currently implement a true new-factor production chain, even though it has a running research loop and a fixed-template submit loop.

**Scope Boundary:** This document audits the upstream core project but does not modify it. It exists in the external monitor workspace so the control plane can continue to describe the core truth without polluting or rewriting the upstream repository.

---

## 1. Executive Conclusion

The upstream project does **not** contain a true new-factor production chain.

What it does contain is:

- a research feedback loop,
- a fixed-template batch simulation and submit loop,
- runtime orchestration for those two loops,
- and runtime-state / submit-summary observability.

What it does **not** contain is:

- dynamic candidate generation output,
- a durable candidate pool,
- a candidate-to-submit bridge,
- or runtime orchestration for a real production workflow.

This is a structural absence, not a localized bug.

## 2. Proven Structure

### 2.1 Runtime Orchestrator

`project_runtime.py` orchestrates only:

- `evolve_skill_preview`
- `submit_batch`

Its `build_job_plan(...)` does not define any job resembling:

- `generate_candidates`
- `build_candidate_pool`
- `evaluate_candidates`
- `select_submitable_candidates`

Therefore the runtime is a two-stage research / submit-test runner, not a production orchestrator.

### 2.2 Research Feedback Script

`scripts/evolve_skill.py` performs:

- user alpha discovery
- PnL fetch
- correlation analysis
- summary generation
- optional local writeback to:
  - `alpha_db.json`
  - `SKILL.md`

It does not produce:

- a durable queue of new expressions,
- a candidate registry for downstream submit consumption,
- or a submit-ready dynamic payload set.

Therefore it is a research memory / audit tool, not a production candidate generator.

### 2.3 Submit Script

`scripts/submit_batch.py` consumes a hardcoded `ALPHAS` list.

It performs:

- simulation
- metric fetch
- threshold gating
- submit attempt
- post-submit status polling
- result persistence to `batch_submit_results.json`

It does not read:

- `alpha_db.json`
- any candidate file
- any runtime-produced candidate registry
- any dynamic queue of generated factors

Therefore it is a fixed-template submit tester, not the consumer stage of a general production chain.

## 3. Missing Chain Diagram

### 3.1 What Exists

```text
project_runtime.py
  -> evolve_skill.py (research snapshot / feedback)
  -> submit_batch.py (fixed template simulate/submit)
```

### 3.2 What Does Not Exist

```text
candidate generation
  -> candidate persistence
  -> candidate evaluation registry
  -> submit bridge
  -> runtime consumption
```

### 3.3 Exact Missing Middle

The absent structural bridge is:

```text
new expression candidate
  -> durable candidate pool
  -> selection / gating
  -> submit consumer
```

That entire middle section is currently missing.

## 4. Root Cause Statement

The root cause is not:

- a failing threshold,
- a broken loop counter,
- a stale state file,
- a monitor-side display bug,
- or a submit API-only issue.

The root cause is:

> `project_runtime.py` is architected as a research feedback runner plus fixed-template submit runner, and never owned the responsibility of orchestrating a new-factor production pipeline.

## 5. Five Missing Layers Required For A Real Production Chain

Any true core repair would need all five of these layers.

### Layer 1: Candidate Generation

Required responsibility:
- create fresh candidate expressions as runtime outputs, not only human playbook examples

Absent today:
- no runtime-generated candidate artifact exists

### Layer 2: Candidate Persistence

Required responsibility:
- write generated candidates into a durable, machine-consumable store

Absent today:
- no candidate pool, queue, registry, or durable candidate file exists

### Layer 3: Candidate Evaluation Registry

Required responsibility:
- store evaluation state for generated candidates before submit

Absent today:
- runtime summary only tracks research progress and fixed submit outcomes

### Layer 4: Submit Bridge

Required responsibility:
- translate evaluated dynamic candidates into submit inputs

Absent today:
- `submit_batch.py` only reads hardcoded `ALPHAS`

### Layer 5: Production-Oriented Runtime Orchestration

Required responsibility:
- schedule and supervise the dynamic production chain end to end

Absent today:
- runtime orchestrates only `evolve_skill_preview` and `submit_batch`

## 6. What The Control Plane Can Truthfully Claim

After the external supervisor upgrades, the monitor workspace may truthfully say:

- the research chain is active
- the submit governance chain is available
- the production chain is absent
- the truth-closure chain is only partial

It must not claim:

- the core project is producing new factors end to end
- the runtime is a complete production orchestrator
- full process uptime implies full business closure

## 7. Recommended Next Core Audit If Work Continues

If future work is allowed in the upstream repository, audit the exact insertion points for:

1. a candidate registry contract
2. a dynamic submit-consumer contract
3. runtime job-plan expansion
4. state-truth definitions for generated candidates
5. monitoring fields for production closure

Until those exist, repeated runtime execution will continue to produce:

- research progress,
- fixed-template submit attempts,
- and monitor-visible activity,

without creating a true new-factor production loop.
