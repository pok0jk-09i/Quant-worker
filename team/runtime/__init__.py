"""Quant worker multi-agent team — runtime operating system (Gen-4 engineering).

This package turns the markdown team OS (CHARTER / STDD_DISCIPLINE /
PROMPT_STANDARD / AGENT_PROMPTS / ROLE_CONTRACT_MATRIX) into RUNNABLE code:

  * ``registry``  — single source of truth for the 8 roles (mirrors
                    PROMPT_STANDARD §1.3/§1.4, zero drift with the docs).
  * ``trace``     — Trace ID (TRC-<EPIC>-<STORY>-<AGENT>-<NN>) + JSONL ledger
                    (Article V 可追溯, the backbone of every decision/artifact).
  * ``orchestrator`` — the Tech Lead's merge authority: dispatches a Story
                    through the role pipeline and the four Merge Gates, then
                    writes a Merge裁决 (merge decision) with a Trace ID.

The four Merge Gates themselves live in ``team/gates/`` and are invoked by
the orchestrator.  Altering any role definition here MUST be reflected in
``ROLE_CONTRACT_MATRIX.md`` — ``registry.validate_against_matrix()`` is a
machine check for that (run by gate_spec / CI).
"""
