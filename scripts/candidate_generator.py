"""Candidate Generator — bridge between research snapshots and submission.

Reads alpha_db.json, identifies high-performing ACTIVE alphas, generates
parameter variants (neutralization/decay/truncation), and writes a
candidates.json file for downstream submission.

Usage:
    cd <skill-dir>
    pyenv exec python scripts/candidate_generator.py

Output:
    candidates.json — list of variant alphas ready for simulation
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))
# R3-B: type-preserving field substitution needs BRAIN field types.
from core.infrastructure.expression_types import load_field_types  # noqa: E402
from core.infrastructure.brain_feedback import apply_feedback_bias  # noqa: E402  (E block)
# R3-C: skip fields that empirically stall BRAIN sims at ~35% (sparse /
# point-in-time / alternative-data fields).  Imported defensively so the
# generator still runs if the guard module is absent.
try:  # noqa: E402
    from core.infrastructure.timeout_field_guard import (  # noqa: E402
        is_timeout_prone,
        TIMEOUT_PRONE_FIELDS,
    )
    _HAS_TIMEOUT_GUARD = True
except Exception:  # pragma: no cover
    is_timeout_prone = None  # type: ignore[assignment]
    TIMEOUT_PRONE_FIELDS = frozenset()  # type: ignore[assignment]
    _HAS_TIMEOUT_GUARD = False

ALPHA_DB_PATH = SKILL_DIR / "alpha_db.json"
CANDIDATES_PATH = SKILL_DIR / "candidates.json"
GUIDANCE_PATH = SKILL_DIR / "generation_guidance.json"

# ── GUIDANCE — injected by evolve_skill --apply ────────────────────
# The guidance file bridges the self-evolution data (SKILL.md Section 12)
# and the candidate generation engine.  It is produced by evolve_skill's
# --apply mode and consumed here on every cycle.
GUIDANCE_MAX_AGE_CYCLES = 2  # cycles after which guidance is considered stale

# ── PARENT SELECTION ──────────────────────────────────────────────
# Wide net. Parents just need to be ACTIVE with non-negative fitness.
# The REAL gate is in candidate_submitter.py (FITNESS≥1.7, SHARPE≥1.5).
# Filtering too hard here is what caused the pipeline drought.
MIN_FITNESS = 0.0      # Exclude negative-fitness alphas only
MIN_SHARPE = -999      # No Sharpe floor — let exploration find surprises
MAX_TURNOVER = 0.50    # Wide — exclude only extreme turnover

# Variant generation — now with EXPLORE mode
NEUTRALIZATION_OPTIONS = ["INDUSTRY", "SUBINDUSTRY", "MARKET", "SECTOR", "NONE"]
DECAY_OPTIONS = [0, 1, 2, 3, 4, 6, 8, 12, 16, 20]
# A1: 0.01 placed FIRST.  truncation=0.01 is the de-facto standard for
# BRAIN-passing alphas (alexisdpc / compasty official mirrors) and is what
# gets past the IND CONCENTRATED_WEIGHT floor; the old list omitted it and
# structurally could never pass that gate.
TRUNCATION_OPTIONS = [0.01, 0.02, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12]

# Introduce randomness so we don't submit the same variants every cycle.
import random  # noqa: E402
VARIANT_SAMPLE_SIZE = 15      # number of random variants per parent (was: generate ALL)
EXPLORE_RATIO = 0.4           # 40% of variants should be random, not just param sweeps

# Maximum candidates per cycle — keep BRAIN simulation budget manageable
MAX_VARIANTS_PER_ALPHA = 12     # Fewer per parent = more parent diversity
MAX_TOTAL_CANDIDATES = 80       # Spread across 6-7 parents, not just top 3
TEMPLATE_RESERVE = 24           # D: budget reserved for economic-template seeds
                              # (pillar ① grounding) — kept separate from the
                              # parent-mutation budget so templates always inject.
COMPOSITE_RESERVE = 12          # F: budget for cross-family composite alphas
                              # (AlphaSAGE adaptive combo of DISTINCT-family
                              # sub-signals; weights from BRAIN IS feedback).
FAMILY_CAP_RATIO = 0.30         # G: max fraction of the pool any single
                              # canonical family may occupy (Hubble family-aware
                              # concentration cap; prevents crowded-template domination).
# Parent-pool budget = remainder after D + F reserves are carved out.
PARENT_RESERVE = MAX_TOTAL_CANDIDATES - TEMPLATE_RESERVE - COMPOSITE_RESERVE

# ── Field substitution (template-based, Phase 0 of variant generation) ───
# Loaded lazily.  Maps category_id → [field_id, ...].
FIELD_SUBSTITUTION_POOL: dict[str, list[str]] | None = None
FIELD_SUBSTITUTE_PER_EXPRESSION = 3  # how many field-substituted expressions per parent
FIELD_SUBSTITUTION_REFERENCE_PATH = SCRIPT_DIR.parent / "references" / "wq_usa_top3000_delay1_data_fields.json"


def _load_field_pool() -> dict[str, list[str]]:
    """Load the 4367-field BRAIN reference and index fields by category."""
    global FIELD_SUBSTITUTION_POOL
    if FIELD_SUBSTITUTION_POOL is not None:
        return FIELD_SUBSTITUTION_POOL
    from collections import defaultdict as _dd3
    import json as _json3
    pool: dict[str, list[str]] = _dd3(list)
    if FIELD_SUBSTITUTION_REFERENCE_PATH.exists():
        ref = _json3.loads(FIELD_SUBSTITUTION_REFERENCE_PATH.read_text(encoding="utf-8"))
        for f in ref:
            cid = f["category"]["id"]
            pool[cid].append(f["id"])
    # Freeze to plain dict
    FIELD_SUBSTITUTION_POOL = dict(pool)
    return FIELD_SUBSTITUTION_POOL


# C: field preference — deprioritise sparse / point-in-time / alternative-data
# fields (analyst guidance & estimates, graph/network ranks, guidance-derived
# fundamentals).  These are low-coverage and statistically the stall-prone /
# weak-signal fields; we still keep them available as a last resort but never
# prefer them when a safer same-type alternative exists.
_ANALYST_OR_ALT_PREFIXES = ("anl4_", "pv13_")
_ANALYST_OR_ALT_SUBSTRINGS = ("_guidance",)


def _is_analyst_or_alt(fid: str) -> bool:
    """True for analyst-guidance / alternative-data fields we should avoid."""
    return (
        fid.startswith(_ANALYST_OR_ALT_PREFIXES)
        or any(s in fid for s in _ANALYST_OR_ALT_SUBSTRINGS)
    )


def _substitute_fields(expression: str, n: int = FIELD_SUBSTITUTE_PER_EXPRESSION) -> list[str]:
    """Generate new expressions by substituting same-category data fields.

    Extracts field-like tokens from the expression, looks each up in the
    4367-field BRAIN reference to determine its category, then swaps in
    alternative fields from the same category.  Returns a list of new
    expression strings (up to ``n``).
    """
    pool = _load_field_pool()
    if not pool:
        return []

    # Build category → [field_id] lookup and field_id → category lookup
    field_to_cat: dict[str, str] = {}
    for cat, fids in pool.items():
        for fid in fids:
            field_to_cat[fid] = cat

    # R3-B: BRAIN field types (MATRIX/VECTOR/GROUP/SYMBOL/UNIVERSE).  Swapping
    # a field for one of a DIFFERENT type is what produced the 44 type-incompatible
    # simulation errors (GROUP/SYMBOL/EVENT fed into ts_*/arith).  We therefore
    # restrict alternatives to the SAME type as the original field.
    field_types = load_field_types()

    # Extract field-like tokens from expression
    # Match identifiers with at least 3 characters and an underscore or digit
    # (operator names like 'rank', 'close' are short; data fields are longer).
    tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]{2,}', expression)
    # Filter to tokens that appear in the field reference
    expr_fields = [t for t in tokens if t in field_to_cat and len(t) > 3]
    if not expr_fields:
        return []

    # For each field in the expression, find 1-2 alternatives
    variants: list[str] = []
    for _ in range(n * 2):  # generate more candidates than needed, pick n best later
        new_expr = expression
        for f in expr_fields:
            cat = field_to_cat[f]
            alternatives = pool.get(cat, [])
            if len(alternatives) < 2:
                continue
            # R3-B: prefer same-type alternatives to keep expressions valid.
            ft = field_types.get(f)
            if ft is not None:
                same_type = [a for a in alternatives if field_types.get(a) == ft]
                if len(same_type) >= 2:
                    alternatives = same_type
            # R3-C: never substitute IN a stall-prone field (BRAIN hangs at
            # ~35% on those sparse/point-in-time/alternative-data fields).
            if _HAS_TIMEOUT_GUARD and TIMEOUT_PRONE_FIELDS:
                alternatives = [a for a in alternatives
                                if a not in TIMEOUT_PRONE_FIELDS]
                if len(alternatives) < 2:
                    continue
            # C: prefer non-analyst / non-alternative-data fields.  Keep the
            # analyst fields only as a fallback when no safer same-type
            # alternative is available (>=2 needed for the swap to proceed).
            if len(alternatives) >= 2:
                safe = [a for a in alternatives if not _is_analyst_or_alt(a)]
                if len(safe) >= 2:
                    alternatives = safe
            # Pick a random alternative different from the current field
            alt = random.choice(alternatives)
            while alt == f and len(alternatives) > 1:
                alt = random.choice(alternatives)
            # Substitute: use word-boundary-aware replacement to avoid
            # partial matches (e.g. 'sales' matching inside 'sales_growth')
            new_expr = re.sub(rf'\b{re.escape(f)}\b', alt, new_expr)
        if new_expr != expression:
            variants.append(new_expr)

    # Deduplicate and sample
    unique = list(dict.fromkeys(variants))
    return unique[:n]


def load_alpha_db() -> dict:
    if not ALPHA_DB_PATH.exists():
        return {"alphas": {}, "last_update": None, "version": 1}
    return json.loads(ALPHA_DB_PATH.read_text(encoding="utf-8"))


def load_generation_guidance() -> dict | None:
    """Load the guidance file if present and fresh.

    Returns ``None`` when the file is missing, malformed, or stale so the
    caller can fall back to the original unguided behaviour without any
    special branching.
    """
    if not GUIDANCE_PATH.exists():
        return None
    try:
        guidance = json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(guidance, dict) or guidance.get("version") != "qf.guidance.v2":
        return None
    source = guidance.get("source_cycle", -1)
    valid_until = guidance.get("valid_until_cycle", -1)
    if source < 0 or valid_until < source:
        return None
    db = load_alpha_db()
    current_cycle = db.get("evolution_round", 0)
    if source + GUIDANCE_MAX_AGE_CYCLES < current_cycle:
        # Stale: caller will degrade to unguided behaviour.
        return None
    return guidance


def select_high_performing_alphas(db: dict, guidance: dict | None = None) -> list[dict]:
    """Select parent alphas with optional guidance enhancement.

    When ``guidance`` is supplied, the parent pool is augmented with
    UNSUBMITTED high-potential alphas from the guidance file and
    confirmed-exhausted patterns are excluded from the systematic-scan
    phase.  Without guidance the behaviour is identical to the original
    implementation.
    """
    candidates = []
    for alpha_id, alpha in db.get("alphas", {}).items():
        if alpha.get("status") != "ACTIVE":
            continue
        fitness = alpha.get("fitness") or 0
        sharpe = alpha.get("sharpe") or 0
        turnover = alpha.get("turnover") or 1
        if fitness >= MIN_FITNESS and sharpe >= MIN_SHARPE and turnover <= MAX_TURNOVER:
            candidates.append({**alpha, "alpha_id": alpha_id})

    # ── Guidance augmentation ────────────────────────────────────
    if guidance:
        # Exclude confirmed-exhausted patterns from the systematic pool.
        exhausted = guidance.get("exhausted_patterns", [])
        blocked_cores = {
            ep["pattern"]
            for ep in exhausted
            if ep.get("exhaustion_level") == "confirmed" and ep.get("action") == "block_systematic_scan"
        }
        if blocked_cores:
            # We import _extract_expression_core lazily; the function lives
            # in evolve_skill.py, but to avoid a circular dependency we
            # replicate the same lightweight core-extraction here.
            import re as _re
            def _core(expr: str) -> str:
                c = _re.sub(r'\b\d+\b', '*', expr)
                depth = 0
                for i, ch in enumerate(c):
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        depth -= 1
                    elif depth == 0 and ch == ',':
                        c = c[:i]
                        break
                return c[:120]
            candidates = [
                c for c in candidates
                if _core(c.get("expression", "")) not in blocked_cores
            ]

        # Augment with UNSUBMITTED high-potential pool.
        unsubmitted = guidance.get("parent_pool", {}).get("unsubmitted_high_potential", [])
        for ua in unsubmitted:
            aid = ua.get("alpha_id")
            if not aid or any(c.get("alpha_id") == aid for c in candidates):
                continue
            entry = db.get("alphas", {}).get(aid, {})
            if not entry:
                continue
            candidates.append({
                **entry,
                "alpha_id": aid,
                "_guidance_source": "unsubmitted_high_potential",
            })

    # Sort by fitness descending
    candidates.sort(key=lambda a: a.get("fitness", 0), reverse=True)
    return candidates


def extract_base_expression(alpha: dict) -> str:
    """Extract the base FASTEXPR expression from alpha data."""
    expr = alpha.get("expression", "")
    if not expr:
        # Try nested structure
        regular = alpha.get("regular", {})
        if isinstance(regular, dict):
            expr = regular.get("code", "")
        elif isinstance(regular, str):
            expr = regular
    return expr


def extract_settings(alpha: dict) -> dict:
    """Extract settings from alpha data, inheriting region/universe from the
    parent alpha.  Fallback to USA/TOP3000 only when the parent carries no
    region information (legacy entries in alpha_db)."""
    settings = alpha.get("settings", {})
    parent_region = alpha.get("region") or settings.get("region", "USA")
    parent_universe = alpha.get("universe") or settings.get("universe", "TOP3000")
    return {
        "instrumentType": settings.get("instrumentType", "EQUITY"),
        "region": parent_region,
        "universe": parent_universe,
        "delay": settings.get("delay", 1),
        # A2: decay default 0 -> 4.  decay~4 controls turnover into the
        # [1%, 70%] band (avoids high-frequency churn) per BRAIN金标准.
        "decay": settings.get("decay", 4),
        "neutralization": settings.get("neutralization", "SUBINDUSTRY"),
        # A2: truncation default 0.08 -> 0.01 (达标alpha标配; passes IND floor).
        "truncation": settings.get("truncation", 0.01),
    }


# B: rank-safe wrap.  BRAIN-passing alphas almost always expose a
# cross-sectional rank as their outermost operator (the golden recipe from
# alexisdpc / compasty).  Wrapping a raw signal in rank() makes it robust and
# unit-less, which is what lifts Sharpe/Fitness past the submission floor.
_RANK_SAFE_OPS = {
    "rank", "zscore", "scale", "group_rank", "group_zscore", "sign",
}


def _top_operator(expr: str) -> str | None:
    """Return the identifier immediately preceding the first '(' of ``expr``
    (the outermost operator call), ignoring a leading unary +/-.

    ``rank(ts_corr(x, y, 20))`` -> ``rank``; ``-ts_delta(close, 5)`` ->
    ``ts_delta``; ``close - open`` -> ``close``; ``rank`` -> None if no call.
    """
    m = re.match(r"^[+\-]?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", expr.strip())
    if m:
        return m.group(1)
    # No function call — bare field arithmetic.  The "top operator" is just
    # the first identifier (not a real operator), so we treat it as unsafe.
    m2 = re.match(r"^[+\-]?\s*([a-zA-Z_][a-zA-Z0-9_]*)", expr.strip())
    return m2.group(1) if m2 else None


def _safe_rank_wrap(expr: str) -> str:
    """Wrap ``expr`` in rank() unless it is already cross-sectionally safe.

    * Already-ranked / scaled / signed / group-ranked at the top -> returned
      unchanged (idempotent).
    * ``trade_when`` / ``if_else`` (conditional envelopes) -> whole expr
      wrapped in rank().
    * Anything else (ts_*, log, arith, bare field) -> rank(expr).
    """
    op = _top_operator(expr)
    if op in _RANK_SAFE_OPS:
        return expr.strip()
    return f"rank({expr.strip()})"


def generate_variants(expression: str, base_settings: dict, max_variants: int = MAX_VARIANTS_PER_ALPHA, substitute: bool = True, feedback_bias: dict | None = None) -> list[dict]:
    """Generate diverse variants: field-substituted expressions + parameter sweep.

    Phase 0 — Field substitution: swap same-category data fields from the
        4367-field BRAIN reference library to produce structurally different
        signals (not just parameter tuning of the same signal).
    Phase 1 — Systematic sweep: neutralization × decay × truncation.
    Phase 2 — Exploration: random parameter combinations (EXPLORE_RATIO).
    Phase 3 — Dedup by (expression, settings) key, then random-sample to
        max_variants.
    """
    # A3: base defaults mirror extract_settings (decay 4, truncation 0.01).
    base_decay = base_settings.get("decay", 4)
    base_neutralization = base_settings.get("neutralization", "SUBINDUSTRY")
    base_truncation = base_settings.get("truncation", 0.01)
    # E block: bias the SWEEP CENTER toward empirically preferred params from
    # real BRAIN IS signal.  This nudges generation toward what BRAIN scored
    # high WITHOUT overriding the deliberate parameter exploration (the sweep
    # still tries other values).  Degradation-first: no feedback -> unchanged.
    if feedback_bias:
        _b = apply_feedback_bias(
            {"decay": base_decay, "truncation": base_truncation,
             "neutralization": base_neutralization}, feedback_bias)
        base_decay = _b["decay"]
        base_truncation = _b["truncation"]
        base_neutralization = _b["neutralization"]

    # Phase 0: Field substitution — produce structurally different expressions
    # (skipped for economic templates so their researched economic meaning
    # stays intact; diversity there comes from the 8 families + param sweep).
    if substitute:
        field_expressions = _substitute_fields(expression)
    else:
        field_expressions = []
    # Always include the original expression so parameter sweep has a baseline
    all_expressions = [expression] + field_expressions

    # Determine how many parameter variants to allocate per expression.
    # If we have multiple expressions, split the budget.
    n_exprs = len(all_expressions)
    params_per_expr = max(4, max_variants // n_exprs)

    variants: list[dict] = []

    for expr_idx, raw_expr in enumerate(all_expressions):
        # B: rank-safe wrap every expression (idempotent if already safe).
        expr = _safe_rank_wrap(raw_expr)
        dest = base_settings
        # For substituted expressions, inherit all settings from parent
        # but flag the source so downstream can trace provenance.
        vtype_prefix = "field_sub" if expr_idx > 0 else "base"

        # Phase 1: Systematic sweep
        for neut in NEUTRALIZATION_OPTIONS:
            if neut == base_neutralization:
                continue
            variants.append({
                "expression": expr,
                "settings": {**dest, "neutralization": neut, "truncation": base_truncation},
                "variant_type": f"{vtype_prefix}:neut={neut}",
            })
        for decay in DECAY_OPTIONS:
            if decay == base_decay:
                continue
            variants.append({
                "expression": expr,
                "settings": {**dest, "decay": decay, "neutralization": base_neutralization},
                "variant_type": f"{vtype_prefix}:decay={decay}",
            })
        for trunc in TRUNCATION_OPTIONS:
            if abs(trunc - base_truncation) < 0.01:
                continue
            variants.append({
                "expression": expr,
                "settings": {**dest, "truncation": trunc, "neutralization": base_neutralization},
                "variant_type": f"{vtype_prefix}:trunc={trunc}",
            })

        # Phase 2: Exploration — random combos
        n_explore = int(params_per_expr * EXPLORE_RATIO)
        for _ in range(n_explore):
            neut = random.choice(NEUTRALIZATION_OPTIONS)
            decay = random.choice(DECAY_OPTIONS)
            trunc = random.choice(TRUNCATION_OPTIONS)
            variants.append({
                "expression": expr,
                "settings": {**dest, "neutralization": neut, "decay": decay, "truncation": trunc},
                "variant_type": f"{vtype_prefix}:explore",
            })

        # Cap per expression
        expr_variants = [v for v in variants if v["expression"] == expr]
        if len(expr_variants) > params_per_expr:
            # Keep the first few + random sample
            keep = expr_variants[:max(3, params_per_expr // 3)]
            rest = expr_variants[max(3, params_per_expr // 3):]
            keep += random.sample(rest, min(params_per_expr - len(keep), len(rest)))
            # Deduplicate and filter out the extras
            variants = [v for v in variants if v["expression"] != expr] + keep

    # Phase 3: Dedup + random-sample (global)
    seen = set()
    unique_variants = []
    for v in variants:
        key = (v["expression"], json.dumps(v["settings"], sort_keys=True))
        if key not in seen:
            seen.add(key)
            unique_variants.append(v)

    if len(unique_variants) > max_variants:
        unique_variants = random.sample(unique_variants, max_variants)
    return unique_variants


def main():
    db = load_alpha_db()
    guidance = load_generation_guidance()  # None if missing or stale
    # E block: real BRAIN IS feedback bias (built by evolve_skill from
    # candidate_submit_results.json's COMPLETE simulations).  Degradation-first:
    # None when guidance is absent/stale, so generation stays unguided.
    feedback_bias = (guidance or {}).get("feedback_bias")
    high_performers = select_high_performing_alphas(db, guidance)
    guidance_tag = " (guidance enhanced)" if guidance else ""
    print(f"Found {len(high_performers)} high-performing parent alphas{guidance_tag} "
          f"(Fitness>={MIN_FITNESS}, Sharpe>={MIN_SHARPE}, TO<={MAX_TURNOVER*100:.0f}%)")

    if not high_performers:
        print("No candidates to generate. Exiting.")
        CANDIDATES_PATH.write_text("[]", encoding="utf-8")
        return 0

    all_candidates: list[dict] = []
    # ── Quality-weighted parent allocation ───────────────────────────
    # Read cluster performance from guidance (built by evolve_skill from
    # 1864+ empirical evaluations across 17+ rounds).  Clusters with
    # higher median Sharpe get proportionally more parent slots.
    #
    # Fallback: equal weighting when guidance is absent or cluster_stats
    # is unavailable.
    sys.path.insert(0, str(SCRIPT_DIR))
    from evolve_skill import classify_alpha as _cf  # type: ignore[import]

    # Group parents by signal cluster
    cluster_pools: dict[str, list[dict]] = defaultdict(list)
    for alpha in high_performers:
        expr = alpha.get("expression", "")
        cluster = _cf(expr, alpha.get("settings")).split("-")[0] or "other"
        cluster_pools[cluster].append(alpha)
    for pool in cluster_pools.values():
        pool.sort(key=lambda a: a.get("fitness", 0), reverse=True)

    # Compute per-cluster quality weights from guidance cluster_stats
    cluster_stats = (guidance or {}).get("cluster_stats", {})
    cluster_weights: dict[str, float] = {}
    if cluster_stats:
        # Weight = median Sharpe, clamped to [0.05, 1.0] so no cluster
        # gets zero slots and no cluster dominates completely.
        raw_weights = {
            c: max(0.05, min(1.0, stats.get("sharpe_median", 0.1)))
            for c, stats in cluster_stats.items()
        }
        total = sum(raw_weights.values()) or 1.0
        cluster_weights = {c: w / total for c, w in raw_weights.items()}
    else:
        # Equal weighting fallback
        cluster_weights = {c: 1.0 / len(cluster_pools) for c in cluster_pools}

    # Weighted round-robin: each cluster gets rounds proportional to weight.
    # A cluster with weight 0.4 gets 4 rounds per cycle; weight 0.1 gets 1.
    # We scale to a discrete number of "slots per cluster" to keep the
    # round-robin simple.
    max_weight = max(cluster_weights.values(), default=0.2)
    cluster_rounds = {
        c: max(1, round(w / max_weight * 4))
        for c, w in cluster_weights.items()
    }

    # Build an ordered schedule: repeat each cluster according to its rounds
    schedule: list[str] = []
    for c in sorted(cluster_pools.keys()):
        schedule.extend([c] * cluster_rounds.get(c, 1))
    # Shuffle within each weight tier so parents from the same cluster
    # are interleaved, not batched.
    random.shuffle(schedule)

    while len(all_candidates) < PARENT_RESERVE and any(cluster_pools.get(c) for c in schedule):
        any_added = False
        for c in schedule:
            if len(all_candidates) >= PARENT_RESERVE:
                break
            if not cluster_pools.get(c):
                continue
            alpha = cluster_pools[c].pop(0)
            alpha_id = alpha.get("alpha_id", "UNKNOWN")
            expression = extract_base_expression(alpha)
            if not expression:
                continue
            base_settings = extract_settings(alpha)
            variants = generate_variants(expression, base_settings, feedback_bias=feedback_bias)
            for v in variants:
                v["source_alpha_id"] = alpha_id
                v["source_fitness"] = alpha.get("fitness")
                v["source_sharpe"] = alpha.get("sharpe")
            c_actual = _cf(expression, base_settings).split("-")[0]
            w = cluster_weights.get(c_actual, 0)
            print(f"  {alpha_id}: {len(variants)} variants "
                  f"(cluster={c_actual}, weight={w:.2f}, "
                  f"Fitness={alpha.get('fitness'):.2f}, Sharpe={alpha.get('sharpe'):.2f})")
            all_candidates.extend(variants)
            any_added = True
        if not any_added:
            break  # all pools exhausted

    all_candidates = all_candidates[:MAX_TOTAL_CANDIDATES]

    # ── D: economic template seeds (pillar ① economic grounding) ──────
    # Inject formulaic alphas with explicit economic hypotheses (mean
    # reversion, value, momentum, liquidity, low-vol, composites) directly
    # from the researched top-playbook — NOT mutated from ghost parents.
    # This diversifies the pool beyond weak-logic parent mutations and is the
    # structural lever for prediction power (research: Kakushadze 101 / jglazar
    # / QuantGPT all anchor on economic meaning + cross-family diversity).
    try:
        from scripts.economic_templates import iter_template_expressions as _iter_tpl
    except Exception:  # pragma: no cover - fallback when run as bare script
        from economic_templates import iter_template_expressions as _iter_tpl
    template_budget = min(TEMPLATE_RESERVE, MAX_TOTAL_CANDIDATES - len(all_candidates))
    if template_budget > 0:
        _fams = list(_iter_tpl())
        _per = max(1, template_budget // len(_fams))
        _added = 0
        for _fam, _expr, _hyp in _fams:
            if _added >= template_budget:
                break
            _tsettings = extract_settings({})  # USA/TOP3000, decay4, trunc0.01
            _vs = generate_variants(_expr, _tsettings, max_variants=_per, substitute=False, feedback_bias=feedback_bias)
            for _v in _vs:
                _v["source"] = "economic_template"
                _v["family"] = _fam
                _v["hypothesis"] = _hyp
                _v["source_fitness"] = None
            all_candidates.extend(_vs)
            _added += len(_vs)
        print(f"  +{_added} economic-template candidates (D)")
    all_candidates = all_candidates[:MAX_TOTAL_CANDIDATES]

    # ── F: cross-family composite alphas (adaptive weighting) ──────
    # Combine DISTINCT economic families into a single mega-alpha (AlphaSAGE
    # dynamic-linear-combo + Kakushadze "combine low-correlated alphas").
    # Each sub-signal is rank-wrapped (golden recipe) and weighted ADAPTIVELY
    # from real BRAIN IS feedback (E block) — grounded, never a gate relax.
    try:
        from scripts.composite_templates import iter_composite_expressions as _iter_comp
    except Exception:  # pragma: no cover - fallback when run as bare script
        from composite_templates import iter_composite_expressions as _iter_comp
    composite_budget = min(COMPOSITE_RESERVE, MAX_TOTAL_CANDIDATES - len(all_candidates))
    if composite_budget > 0:
        _cadded = 0
        for _cname, _cexpr, _chyp in _iter_comp(feedback_bias):
            if _cadded >= composite_budget:
                break
            _cc = {
                "expression": _cexpr,
                "settings": extract_settings({}),  # USA/TOP3000, decay4, trunc0.01
                "source": "composite",
                "family": "composite:" + _cname,
                "hypothesis": _chyp,
                "source_fitness": None,
            }
            all_candidates.append(_cc)
            _cadded += 1
        print(f"  +{_cadded} composite candidates (F)")

    # R3-C: drop any candidate (parent expression OR field-substituted
    # variant) that touches an empirically stall-prone field.  BRAIN hangs
    # at ~35% on those sparse/point-in-time/alternative-data fields, so we
    # never even spawn a simulation that will waste the 600s poll window.
    if _HAS_TIMEOUT_GUARD and is_timeout_prone is not None:
        before = len(all_candidates)
        all_candidates = [
            c for c in all_candidates
            if not is_timeout_prone(c.get("expression", ""))
        ]
        dropped = before - len(all_candidates)
        if dropped:
            print(f"  R3-C: dropped {dropped} timeout-prone candidate(s)")

    # ── G: family-diversity gate (Hubble family-aware concentration cap) ──
    # No single canonical family may crowd the pool; over-represented families
    # are trimmed from the tail.  This is the family-aware analogue of Hubble's
    # crowding penalty and enforces the "diversity by construction" pillar.
    try:
        from core.infrastructure.family_classifier import enforce_family_diversity
        before = len(all_candidates)
        all_candidates = enforce_family_diversity(all_candidates, cap_ratio=FAMILY_CAP_RATIO)
        dropped = before - len(all_candidates)
        if dropped:
            print(f"  G: capped {dropped} over-represented-family candidate(s)")
    except Exception:  # pragma: no cover - guard module absent
        pass

    CANDIDATES_PATH.write_text(json.dumps(all_candidates, indent=2), encoding="utf-8")
    print(f"\nGenerated {len(all_candidates)} total candidates → {CANDIDATES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
