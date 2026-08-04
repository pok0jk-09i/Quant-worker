"""Timeout-prone field guard (R3-C / R3-A safety net).

WHY THIS EXISTS
---------------
Empirical analysis of ``candidate_submit_results.json`` (27 TIMEOUT vs 42
COMPLETE sims over the 2026-08-01 restart cycle) showed that BRAIN
simulations hang at a *fixed* ~35% progress and never recover — these are
NOT slow sims (slow = progress keeps advancing) and NOT a local
``POLL_TIMEOUT`` mis-calibration (raising it would not help: progress is
frozen, not creeping).  The hang is a BRAIN-side stall on specific fields.

Crucially, within the *same* operator template (the
``ts_corr``/``trade_when``/``log``/``zscore``/``winsorize``/``greater``/
``ts_backfill``/``ts_mean`` "Family B" signature, which appears in both
TIMEOUT and COMPLETE records), the **field** cleanly separates the two
outcomes:

* 14 fields appeared ONLY in TIMEOUT records (T>=2, C=0) -> 100% stall.
  These are predominantly sparse / point-in-time / alternative-data fields
  (``anl4_*`` analyst guidance & estimates, ``pv13_*`` graph/network ranks,
  ``max_*_guidance_*``, plus a handful of fundamentals when wrapped in
  ``ts_backfill(field, 120)``).  BRAIN's backfill/eval stage chokes on
  their coverage gaps and freezes at 35%.
* 7 fields appeared ONLY in COMPLETE records (C>=1, T=0) -> 0% stall.
* The single shared field ``pv13_com_page_rank`` (T=4, C=3, rate 0.57) is
  NOT deterministic, so it is deliberately excluded from the blocklist.

This guard therefore does TWO things:
* R3-C (generation): ``candidate_generator`` drops any candidate whose
  expression touches a blocklisted field, so we never even spawn a sim
  that will hang.
* R3-A (submission): ``candidate_submitter`` returns
  ``sim.status == "SKIPPED_TIMEOUT_RISK"`` *before* borrowing a session or
  polling, recovering the full 600s poll window that would otherwise be
  wasted on a guaranteed stall.

The blocklist is DATA-DERIVED, not hand-guessed: ``TIMEOUT_PRONE_FIELDS``
below is the curated PREVENTION core (every field the empirical data has ever
shown to stall).  At runtime ``effective_timeout_blocklist()`` unions it with
``rebuild_timeout_blocklist()`` over the live results file, so newly observed
100%-stall fields are blocked automatically and the guard can never develop a
hole as the data drifts.  No manual rebuild step is needed.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

# ── Provenance threshold ───────────────────────────────────────────
# A field enters the blocklist only if it appears in >= this many TIMEOUT
# records AND in zero COMPLETE records.  T>=2 keeps us off single-sample
# flukes; C==0 is what makes the signal deterministic in observed data.
MIN_TIMEOUT_COUNT = 2

# ── Never-block core market fields ─────────────────────────────────
# These are universally-covered BRAIN market fields (price / volume /
# microstructure).  They have 100% daily coverage, so BRAIN's
# backfill/eval stage can NEVER stall on them — a TIMEOUT signal on one of
# these is always a small-sample artifact, not a real stall.  The
# data-derived rebuild MUST exclude them, otherwise a fluke (e.g. ``open``
# appearing in 2 TIMEOUT records and 0 COMPLETE records in a sparse slice)
# would poison the effective blocklist and break generation of perfectly
# valid factors like ``ts_mean(open, 20)`` or ``adv20 / open``.  This is a
# hard invariant, not a heuristic: the effective blocklist is computed as
# ``(frozen ∪ rebuilt) − NEVER_BLOCK_CORE``.
NEVER_BLOCK_CORE: frozenset[str] = frozenset({
    "open", "close", "high", "low", "volume", "returns", "adv", "vwap",
    "amount", "preclose", "pctchange", "high_limit", "low_limit",
    "open_t", "close_t", "high_t", "low_t", "volume_t", "returns_t",
    "money", "deal_amount", "deal_volume", "deal_money", "adjfactor",
})

# ── Field extraction ───────────────────────────────────────────────
# Mirrors the validated extractor used during the analysis: strip operator
# names, keyword args, bare numbers, and ALL-CAPS constants (e.g. PI),
# leaving only data-field identifiers.
_KWARGS = {
    "std", "decay", "nan", "on", "off", "true", "false", "null", "none",
    "inf", "pi", "version",
}
_FUNCS = {
    "trade_when", "greater", "less", "equal", "rank", "zscore", "log",
    "sqrt", "abs", "winsorize", "scale", "normalize", "sigmoid", "tanh",
    "fractional", "sign", "exp",
    "ts_mean", "ts_sum", "ts_std_dev", "ts_min", "ts_max", "ts_rank",
    "ts_zscore", "ts_delta", "ts_corr", "ts_regression", "ts_backfill",
    "ts_arg_max", "ts_arg_min", "ts_product", "ts_ir",
    "group_rank", "group_zscore", "group_scale", "group_mean",
    "group_neutralize", "group_backfill", "group_arg_max", "group_arg_min",
    "vec_avg", "vec_sum", "vec_min", "vec_max", "vec_std",
    "inverse", "densify", "delay", "to_percent", "regression_neut",
}


def extract_fields(expr: str) -> list[str]:
    """Return the data-field identifiers used in a FASTEXPR expression.

    Operators, keyword args (std/decay/...), bare numbers and ALL-CAPS
    constants are excluded so only genuine BRAIN data fields remain.
    """
    if not expr:
        return []
    toks = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr)
    out: list[str] = []
    for t in toks:
        if t in _FUNCS or t in _KWARGS:
            continue
        if t.isdigit():
            continue
        # ALL-CAPS with no underscore (e.g. PI, INF) is a numeric constant.
        if re.search(r"[A-Z]", t) and "_" not in t:
            continue
        out.append(t)
    return out


# ── Frozen blocklist (regenerated by rebuild_timeout_blocklist) ─────
# This is the PREVENTION artifact: it is intentionally a SUPERSET of every
# field the empirical data has ever shown to stall (T>=2, C==0).  We keep
# historical fields even after the guard has suppressed them from new
# results, because they remain 100%-stall risks if any template re-introduces
# them.  The set is:
#   * 14 fields from candidate_submit_results.json, 2026-08-01 cycle
#     (27 TIMEOUT, 42 COMPLETE) — analyst guidance/estimate, pv13 graph ranks,
#     and a few fundamentals under ts_backfill.
#   * + 5 fields re-derived from the CURRENT candidate_submit_results.json
#     (free_cash_flow_per_share, net_profit_adjusted_value, op_cash_flow_median,
#     rel_ret_cust, rel_ret_part) — cash-flow / relative-return fields that now
#     show T>=2, C==0 but were NOT in the original 2026-08-01 set (the guard had
#     a hole).  Added 2026-08-04 during Gen-4 gate validation.
# Re-run rebuild_timeout_blocklist() as more data accumulates to keep honest.
TIMEOUT_PRONE_FIELDS: frozenset[str] = frozenset({
    # analyst guidance / estimate (point-in-time, sparse)
    "anl4_fs_guidances_advanced_af_nd_epsr_maxguidance",
    "anl4_fs_detail_estimate_1qf_v4_nd_sh_equity_median",
    "max_book_value_per_share_guidance_2",
    "max_gross_income_guidance_2",
    # pv13 graph / network ranks (alternative data, sparse coverage)
    "pv13_ustomergraphrank_auth_rank",
    "pv13_ustomergraphrank_page_rank",
    "pv13_com_rk_au",
    "pv13_revere_zipcode",
    "pv13_ompetitorgraphrank_hub_rank",
    # fundamentals (stall only when wrapped in ts_backfill in Family B)
    "cap",
    "net_income_total_2",
    "net_debt_reported_value",
    "research_development_expense_reported_value",
    "rel_ret_comp",
    # cash-flow / relative-return fields re-derived from CURRENT results
    # (were a hole in the original 2026-08-01 set; 100% stall in new data)
    "free_cash_flow_per_share",
    "net_profit_adjusted_value",
    "op_cash_flow_median",
    "rel_ret_cust",
    "rel_ret_part",
})


def timeout_prone_fields_in(expr: str) -> list[str]:
    """Return the blocklisted fields present in ``expr`` (empty = safe)."""
    if not expr:
        return []
    fields = set(extract_fields(expr))
    return sorted(fields & _EFFECTIVE)


def is_timeout_prone(expr: str) -> bool:
    """True if ``expr`` uses any empirically stall-prone field."""
    return bool(timeout_prone_fields_in(expr))


def rebuild_timeout_blocklist(
    results_path: str | Path,
    min_timeout: int = MIN_TIMEOUT_COUNT,
) -> set[str]:
    """Re-derive the blocklist from a real submission-results file.

    Scans every record, tallies per-field TIMEOUT/COMPLETE counts, and
    returns the set of fields with ``T >= min_timeout`` and ``C == 0``.
    Use this (not the frozen constant) as more data accumulates, so the
    guard stays evidence-based instead of a stale hand-picked list.
    """
    p = Path(results_path)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    recs = data if isinstance(data, list) else (
        data.get("results") or data.get("items") or []
    )

    to = Counter()
    co = Counter()
    for r in recs:
        sim = r.get("sim") or {}
        st = sim.get("status")
        if st not in ("TIMEOUT", "COMPLETE"):
            continue
        cand = r.get("candidate") or {}
        expr = (cand.get("expression") or "").strip()
        if not expr:
            continue
        for f in set(extract_fields(expr)):
            if f in NEVER_BLOCK_CORE:
                continue
            (to if st == "TIMEOUT" else co)[f] += 1

    return {f for f in to if to[f] >= min_timeout and co.get(f, 0) == 0}


# ── Effective (drift-proof) blocklist ─────────────────────────────
# The curated ``TIMEOUT_PRONE_FIELDS`` above is the HISTORICAL PREVENTION
# core.  But the live submission-results file keeps accumulating new
# candidate sims, and the empirical stall set DRIFTS: fields that were safe
# last week stall this week, and vice-versa.  A purely hand-maintained
# frozen list therefore develops HOLES every time the live system writes
# new results (this broke the gate twice during Gen-4 validation).
#
# The fix: the *effective* blocklist is the frozen core UNIONED with the
# data-derived set from the current results file.  The guard can then never
# develop a hole — whatever the live data shows as 100%-stall is blocked
# automatically.  If the results file is absent (fresh checkout / CI without
# it), we fall back to the curated core only.  Computed at import; cosmic-ray
# mutation workers re-read it per run.
_RESULTS_DEFAULT = Path(__file__).resolve().parents[2] / "candidate_submit_results.json"


def effective_timeout_blocklist(
    results_path: str | Path | None = None,
) -> frozenset[str]:
    """Frozen core ∪ current data-derived stall set (drift-proof)."""
    rebuilt = rebuild_timeout_blocklist(
        results_path if results_path is not None else _RESULTS_DEFAULT
    )
    return (TIMEOUT_PRONE_FIELDS | rebuilt) - NEVER_BLOCK_CORE


_EFFECTIVE = effective_timeout_blocklist()
