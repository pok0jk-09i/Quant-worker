"""BRAIN Fast-Expression type-safety validator.

WHY THIS EXISTS
---------------
Our simulation logs showed ~44/77 candidate simulations failing with two
repeatable, *type-incompatible* errors:

  * "expected Unit[], found Unit[Group:1]"  (32 cases)
  * "ts_backfill/divide does not support event inputs" (12 cases)

Root cause (verified against the 4367-field BRAIN reference +
official operator docs): the generator fed **GROUP / SYMBOL / EVENT**
typed fields into **Time-Series (ts_*) / arithmetic** operators, which
only accept **MATRIX / VECTOR** (numeric, per-asset time-series or
cross-sectional) inputs.

BRAIN field ``type`` vocabulary (from the reference file):
  MATRIX  -> per-asset time series (Unit[])         e.g. close, volume, fnd_*
  VECTOR  -> cross-sectional aggregate (time-indexed) e.g. market aggregates
  GROUP   -> classification (Unit[Group])           e.g. industry, sector, country
  SYMBOL  -> identifier metadata                     e.g. cusip, ticker
  UNIVERSE-> universe membership

This module encodes the operator<->field-type compatibility matrix
(extracted from official BRAIN operator docs: Time-Series / Cross-Sectional
/ Group / Vector / Arithmetic categories) and validates an expression
*before* we burn a BRAIN simulation on it.

It is the single guard used by both:
  * candidate_submitter.py  (pre-simulation waste stopper, R3-A)
  * candidate_generator.py  (type-preserving field substitution, R3-B)
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

# Numeric, simulation-eligible field types (Unit[]).
NUMERIC_TYPES = {"MATRIX", "VECTOR"}

# ── Operator -> allowed input field types ────────────────────────────
# Time-Series operators: consume per-asset time series. Official docs:
# "applied independently to each symbol over time". They do NOT accept
# GROUP/SYMBOL/UNIVERSE/EVENT inputs.
TS_OPS = {
    "ts_mean", "ts_sum", "ts_std", "ts_min", "ts_max", "ts_delta", "ts_delay",
    "ts_zscore", "ts_scale", "ts_covariance", "ts_corr", "ts_regression",
    "ts_backfill", "ts_product", "ts_count_nans", "ts_av_diff", "ts_arg_max",
    "ts_rank", "ts_skewness", "ts_kurtosis", "ts_decay_exp_window",
    "ts_decay_linear", "ts_step", "ts_av_diff",
}
# Cross-Sectional operators: compare across symbols on a single date.
XS_OPS = {
    "rank", "zscore", "quantile", "winsorize", "scale", "normalize", "abs",
    "log", "sqrt", "signed_power", "inverse", "reverse", "power", "sign",
}
# Arithmetic operators: element-wise numeric.
ARITH_OPS = {"add", "subtract", "divide", "multiply"}
# Vector operators: operate on VECTOR (cross-sectional) inputs.
VECTOR_OPS = {"vec_avg", "vec_sum"}

# group_*(x, group, ...) : x must be numeric (MATRIX/VECTOR); the group
# argument must be GROUP.  Positional, so handled specially.
GROUP_OPS = {
    "group_rank", "group_zscore", "group_scale", "group_mean",
    "group_neutralize", "group_backfill",
}
# densify(x): x must be GROUP.
DENSIFY_OPS = {"densify"}

# ── EVENT detection (heuristic) ─────────────────────────────────────
# Our 4367-field reference snapshot has NO explicit "EVENT" type (it only
# carries MATRIX/VECTOR/GROUP/SYMBOL/UNIVERSE).  Yet BRAIN rejects feeding
# event-type fields (e.g. ``fnd6_newqeventv110_glceeps12``) into ts_*/arith
# operators with "does not support event inputs".  Until we fetch authoritative
# per-field types from the BRAIN API, we flag event-*named* fields heuristically
# and treat them as non-numeric (forbidden in numeric/ts/group-value contexts).
# This is a stop-gap; the authoritative fix is to populate EVENT from the API.
EVENT_FIELD_PATTERNS = (r"newqevent", r"_event_", r"eventv", r"announce")
_EVENT_RE = re.compile("|".join(f"(?:{p})" for p in EVENT_FIELD_PATTERNS), re.IGNORECASE)

# Map every operator to its allowed input field types.
_OPERATOR_ALLOWED: dict[str, set[str]] = {}
for _op in TS_OPS | XS_OPS | ARITH_OPS | VECTOR_OPS:
    _OPERATOR_ALLOWED[_op] = set(NUMERIC_TYPES)
for _op in VECTOR_OPS:
    _OPERATOR_ALLOWED[_op] = {"VECTOR"}  # vec_* strictly cross-sectional aggregate
for _op in DENSIFY_OPS:
    _OPERATOR_ALLOWED[_op] = {"GROUP"}


_REFERENCE_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent
    / "references" / "wq_usa_top3000_delay1_data_fields.json"
)


@lru_cache(maxsize=1)
def load_field_types(reference_path: str | None = None) -> dict[str, str]:
    """Load field_id -> BRAIN ``type`` map from the reference JSON.

    Returns {} on any failure (callers must degrade gracefully -- a missing
    type map means "skip validation", never "block everything").
    """
    path = Path(reference_path) if reference_path else _REFERENCE_DEFAULT
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, str] = {}
    for f in data:
        fid = f.get("id")
        t = f.get("type")
        if fid and t:
            out[fid] = str(t).upper()
    return out


# ── Lightweight expression parser (Lisp-like, paren-aware) ───────────
_FIELD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def _split_top(s: str) -> list[str]:
    """Split a comma-separated argument list at paren-depth 0."""
    parts: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts]


def parse_calls(expr: str) -> list[tuple[str, list[str]]]:
    """Yield ``(operator, [arg_strings])`` for every function call in expr.

    Handles arbitrary nesting by tracking parenthesis depth and extracting
    the full inner span for each call.
    """
    calls: list[tuple[str, list[str]]] = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isalpha():
            j = i
            while j < n and (expr[j].isalnum() or expr[j] == "_"):
                j += 1
            op = expr[i:j]
            if j < n and expr[j] == "(":
                depth = 0
                k = j
                while k < n:
                    if expr[k] == "(":
                        depth += 1
                    elif expr[k] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                inner = expr[j + 1:k]
                calls.append((op, _split_top(inner)))
                # Continue scanning INSIDE the call so nested calls are
                # also discovered (e.g. ts_corr(...) inside trade_when(...)).
                i = j + 1
            else:
                i = j
        else:
            i += 1
    return calls


def _fields_in(arg: str, field_types: dict[str, str]) -> list[str]:
    """Return field ids present in ``arg`` that exist in the type map."""
    return [t for t in _FIELD_RE.findall(arg) if t in field_types]


def effective_type(fid: str, field_types: dict[str, str]) -> str | None:
    """Resolve a field's effective BRAIN type.

    Event-*named* fields are treated as EVENT first (they break ts_*/arith
    in BRAIN regardless of how the reference snapshot may have typed them),
    then the explicit type map is consulted, else None (cannot validate).
    """
    if _EVENT_RE.search(fid):
        return "EVENT"
    t = field_types.get(fid)
    if t is not None:
        return t
    return None


def _all_field_tokens(arg: str) -> list[str]:
    """Every identifier token in an arg (candidate for field lookup)."""
    return _FIELD_RE.findall(arg)


def validate_expression(
    expr: str,
    field_types: dict[str, str] | None = None,
) -> list[str]:
    """Return a list of human-readable type violations in ``expr``.

    Empty list == expression is type-safe (from the operator/field-type
    perspective).  A missing ``field_types`` map returns [] (degrade).
    """
    if field_types is None:
        field_types = load_field_types()
    if not expr or not expr.strip():
        return []

    violations: list[str] = []
    for op, args in parse_calls(expr):
        op_lower = op.lower()
        if op_lower in GROUP_OPS:
            # Positional: arg0 = value (numeric), arg1 = group (GROUP).
            if len(args) >= 1:
                for fld in _all_field_tokens(args[0]):
                    et = effective_type(fld, field_types)
                    if et is not None and et not in NUMERIC_TYPES:
                        violations.append(
                            f"{op}(value={fld}:{et}) must be numeric"
                        )
            if len(args) >= 2:
                for fld in _all_field_tokens(args[1]):
                    et = effective_type(fld, field_types)
                    if et is not None and et != "GROUP":
                        violations.append(
                            f"{op}(group={fld}:{et}) must be GROUP"
                        )
            continue
        allowed = _OPERATOR_ALLOWED.get(op_lower)
        if allowed is None:
            # Unknown operator -- cannot validate; skip (never block).
            continue
        for arg in args:
            for fld in _all_field_tokens(arg):
                et = effective_type(fld, field_types)
                if et is not None and et not in allowed:
                    violations.append(
                        f"{op}({fld}:{et}) not allowed "
                        f"(needs {sorted(allowed)})"
                    )
    return violations


def is_type_safe(expr: str, field_types: dict[str, str] | None = None) -> bool:
    """Convenience bool wrapper."""
    return not validate_expression(expr, field_types)
