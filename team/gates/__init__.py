"""Four Merge Gates (Gen-4 engineering).

Each module exposes ``run(epic, story, trace_id) -> (ok: bool, detail: dict)``
so the orchestrator can chain them in order and record a verdict.

  门① spec.py       — spec coverage (GWT + interface contract + referencing test)
  门② tests.py      — lint + full pytest (unit / integration / PBT)
  门③ contract.py   — consumer-driven contract tests
  门④ qa.py         — independent evaluator: lint + tests + cosmic-ray mutation
"""
