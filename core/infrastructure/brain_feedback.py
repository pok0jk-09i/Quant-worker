"""E block — BRAIN in-sample (IS) feedback bias.

This is the CORRECT feedback path.  Every COMPLETE simulation returns
``is_metrics`` (sharpe / fitness / turnover) which is the ONLY reliable
ground truth for factor quality (AlphaBench, ICLR 2026: local proxies are
near-random; BRAIN IS is truth).  We aggregate per-feature quality so the
next generation is biased toward what BRAIN actually scored high —
**without ever submitting low-quality alphas just to learn**.

Contrast with the wrong path (rejected 2026-08-02): relaxing the submission
gate to BRAIN's floor so that "something submits" is submitting for the sake
of submitting.  The user wants HIGH-STANDARD factors submitted; quality is
raised by learning from REAL IS signal, not by lowering the bar.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

# Operator = identifier immediately followed by '('.
_OP_RE = re.compile(r"([A-Za-z_]\w*)\s*\(")
# Any identifier (used to find fields = identifiers NOT followed by '(').
_ID_RE = re.compile(r"[A-Za-z_]\w*")


def extract_operators(expr: str) -> list[str]:
    """Return operator names used in ``expr`` (e.g. ts_zscore, rank)."""
    return _OP_RE.findall(expr)


def extract_fields(expr: str) -> list[str]:
    """Return field names in ``expr`` (identifiers not followed by '(').

    Operators (followed by '(') and bare numeric constants are excluded.
    """
    ops = set(extract_operators(expr))
    fields: list[str] = []
    for m in _ID_RE.finditer(expr):
        tok = m.group(0)
        if expr[m.end():m.end() + 1] == "(":
            continue  # operator call
        if tok in ops:
            continue
        fields.append(tok)
    return fields


def _summarize(acc: dict) -> dict:
    return {
        k: {"mean": round(statistics.mean(v), 3), "n": len(v)}
        for k, v in acc.items()
    }


def _prefer(acc: dict, min_n: int = 2):
    """Return the feature value with the highest mean score (>= min_n samples)."""
    best, best_mean = None, -1e18
    for k, vals in acc.items():
        if len(vals) >= min_n:
            m = statistics.mean(vals)
            if m > best_mean:
                best_mean, best = m, k
    return best


def _top_keys(acc: dict, k: int = 8, min_n: int = 1) -> list:
    items = [(key, statistics.mean(v)) for key, v in acc.items() if len(v) >= min_n]
    items.sort(key=lambda x: x[1], reverse=True)
    return [key for key, _ in items[:k]]


def build_feedback_bias(results_path, quality_key: str = "sharpe") -> dict:
    """Aggregate BRAIN IS signal from simulation results into a generation bias.

    Reads ``candidate_submit_results.json`` (or any list of result entries),
    keeps only COMPLETE entries that carry ``is_metrics``, and computes per-
    feature mean quality (default: sharpe).  Returns a dict with operator /
    field / param means plus the preferred decay / truncation / neutralization
    and the top recipes.  Degradation-first: on any failure returns
    ``{"available": False}`` so callers fall back to unguided behaviour.
    """
    try:
        data = json.loads(Path(results_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "n_samples": 0}
    if not isinstance(data, list):
        data = []

    op_acc: dict = defaultdict(list)
    field_acc: dict = defaultdict(list)
    decay_acc: dict = defaultdict(list)
    trunc_acc: dict = defaultdict(list)
    neut_acc: dict = defaultdict(list)
    region_acc: dict = defaultdict(list)
    universe_acc: dict = defaultdict(list)
    family_acc: dict = defaultdict(list)
    recipes: list = []
    n = 0

    for e in data:
        sim = e.get("sim") or {}
        if sim.get("status") != "COMPLETE":
            continue
        im = e.get("is_metrics") or {}
        score = im.get(quality_key)
        if not isinstance(score, (int, float)):
            continue
        cand = e.get("candidate") or {}
        expr = cand.get("expression") or ""
        if not expr:
            continue
        n += 1
        ops = set(extract_operators(expr))
        for o in ops:
            op_acc[o].append(score)
        for fld in set(extract_fields(expr)):
            field_acc[fld].append(score)
        st = cand.get("settings") or {}
        d, t, nt = st.get("decay"), st.get("truncation"), st.get("neutralization")
        rg, uv = st.get("region"), st.get("universe")
        if isinstance(d, (int, float)):
            decay_acc[d].append(score)
        if isinstance(t, (int, float)):
            trunc_acc[t].append(score)
        if isinstance(nt, str):
            neut_acc[nt].append(score)
        if isinstance(rg, str):
            region_acc[rg].append(score)
        if isinstance(uv, str):
            universe_acc[uv].append(score)
        fam = cand.get("family")
        if isinstance(fam, str):
            family_acc[fam].append(score)
        recipes.append((score, expr))

    if n == 0:
        return {"available": False, "n_samples": 0}

    recipes.sort(key=lambda x: x[0], reverse=True)
    return {
        "available": True,
        "quality_key": quality_key,
        "n_samples": n,
        "mean_score": round(statistics.mean(r[0] for r in recipes), 3),
        "best_score": recipes[0][0],
        "operator_mean": _summarize(op_acc),
        "field_mean": _summarize(field_acc),
        "decay_mean": _summarize(decay_acc),
        "truncation_mean": _summarize(trunc_acc),
        "neutralization_mean": _summarize(neut_acc),
        "region_mean": _summarize(region_acc),
        "universe_mean": _summarize(universe_acc),
        "family_mean": _summarize(family_acc),
        "preferred_decay": _prefer(decay_acc),
        "preferred_truncation": _prefer(trunc_acc),
        "preferred_neutralization": _prefer(neut_acc),
        "top_operators": _top_keys(op_acc),
        "top_fields": _top_keys(field_acc),
        "top_recipes": [{"score": s, "expression": x} for s, x in recipes[:10]],
    }


def apply_feedback_bias(base_settings: dict, feedback_bias: dict | None) -> dict:
    """Nudge ``base_settings`` toward empirically preferred params.

    Pure, degradation-first: with no feedback (or ``available`` False) the
    settings are returned unchanged.  Only decay / truncation / neutralization
    are nudged — the high-level economic intent of the variant is preserved.
    """
    if not feedback_bias or not feedback_bias.get("available"):
        return base_settings
    out = dict(base_settings)
    pd = feedback_bias.get("preferred_decay")
    pt = feedback_bias.get("preferred_truncation")
    pn = feedback_bias.get("preferred_neutralization")
    if isinstance(pd, (int, float)):
        out["decay"] = pd
    if isinstance(pt, (int, float)):
        out["truncation"] = pt
    if isinstance(pn, str):
        out["neutralization"] = pn
    return out
