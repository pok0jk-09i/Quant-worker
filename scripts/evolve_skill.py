"""WQ Alpha Research Skill self-evolution helper.

Self-contained: only needs `requests`, `numpy`, and credentials supplied via
environment variables or a local untracked `credential.txt` file.

Usage:
    cd <skill-dir>
    pyenv exec python scripts/evolve_skill.py
    pyenv exec python scripts/evolve_skill.py --apply

Behavior:
    - First run (empty alpha_db.json): bulk snapshot.
    - Subsequent runs: incremental entries for new/changed alphas.
    - Without --apply: prints proposed markdown snippet, modifies nothing.
    - With --apply: appends snippet to SKILL.md Section 12 and saves alpha_db.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
from requests.auth import HTTPBasicAuth

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ALPHA_DB_PATH = SKILL_DIR / "alpha_db.json"
SKILL_PATH = SKILL_DIR / "SKILL.md"
CREDENTIAL_PATH = SKILL_DIR / "credential.txt"
GUIDANCE_PATH = SKILL_DIR / "generation_guidance.json"

API_BASE = "https://api.worldquantbrain.com"

HEADERS = {
    "Accept": "application/json;version=2.0",
    "Content-Type": "application/json",
}


def emit_stage_progress(stage: str, detail: str) -> None:
    # Windows pipe print(flush=True) + non-ASCII → OSError 22.
    # Use plain print without flush; project_runtime reads via PIPE + bufsize=1.
    sys.stdout.write(f"stage: {stage} | {detail}\n")
    sys.stdout.flush()


def load_credentials() -> tuple[str, str]:
    """Load BRAIN credentials without relying on committed secrets."""
    env_user = os.getenv("WQ_BRAIN_USERNAME")
    env_password = os.getenv("WQ_BRAIN_PASSWORD")
    if env_user and env_password:
        return env_user, env_password

    candidates = [
        CREDENTIAL_PATH,
        Path.cwd() / "credential.txt",
    ]
    for p in candidates:
        if p.exists():
            username, password = json.loads(p.read_text(encoding="utf-8"))
            return str(username), str(password)
    raise FileNotFoundError(
        "BRAIN credentials not found. Set WQ_BRAIN_USERNAME/WQ_BRAIN_PASSWORD "
        'or create an untracked credential.txt with ["your_username", "your_password"].'
    )


def create_session() -> requests.Session:
    username, password = load_credentials()
    session = requests.Session()
    session.auth = HTTPBasicAuth(username, password)
    session.headers.update(HEADERS)

    resp = session.post(f"{API_BASE}/authentication")
    if resp.status_code != 201:
        raise RuntimeError(f"BRAIN auth failed: {resp.status_code} {resp.text}")
    return session


def reauth_if_needed(session: requests.Session) -> bool:
    """Re-authenticate when the session has expired or is about to.

    Returns True if re-authentication was performed, False if session is still valid.
    """
    try:
        resp = session.get(f"{API_BASE}/users/self", timeout=10)
        if resp.status_code == 200:
            return False  # Session still valid
        if resp.status_code != 401:
            return False
    except Exception:
        # Connection error — assume session is invalid, try re-auth
        pass

    # Re-authenticate
    try:
        load_credentials()
        # The session.auth stays as HTTPBasicAuth so re-posting /authentication
        # exchanges the credentials for a fresh JWT.
        resp = session.post(f"{API_BASE}/authentication", timeout=30)
        if resp.status_code == 201:
            return True
    except Exception:
        pass
    return False


def get_with_retry(
    session: requests.Session,
    url: str,
    retries: int = 50,
    max_rate_limit_retries: int = 50,
    **kwargs,
) -> requests.Response:
    """HTTP GET with full retry support: 429, 401, ConnectionError, Timeout.

    Parameters aligned to BRAIN community standards (wqb library uses 600):
      retries=50: ConnectionError/Timeout attempts before giving up.
      max_rate_limit_retries=50: 429 attempts before giving up.
      Backoff floor raised to 10s (community min is 60s for batch pause).
    """
    rate_limit_attempts = 0
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=(10, 30), **kwargs)
            if resp.status_code == 429:
                rate_limit_attempts += 1
                if rate_limit_attempts > max_rate_limit_retries:
                    raise RuntimeError(
                        f"GET {url} rate-limited {max_rate_limit_retries} times in a row"
                    )
                retry_after_raw = resp.headers.get("Retry-After", "10")
                try:
                    retry_after = min(int(retry_after_raw), 120)
                except (ValueError, TypeError):
                    retry_after = 10
                # Exponential backoff on repeated 429s, capped at 600s
                backoff = min(retry_after * (2 ** (rate_limit_attempts - 1)), 600)
                emit_stage_progress("rate_limited", f"429 retry {rate_limit_attempts}/{max_rate_limit_retries} wait {backoff}s")
                print(
                    f"[429] {url} — waiting {backoff}s (attempt {rate_limit_attempts})",
                    flush=True,
                )
                time.sleep(backoff)
                continue
            if resp.status_code == 401:
                # Session expired, re-auth and retry
                if reauth_if_needed(session):
                    print(f"[401] re-authenticated, retrying {url}", flush=True)
                    continue
                # Re-auth failed
                raise RuntimeError(f"GET {url} 401 — re-auth failed")
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            emit_stage_progress("timeout_retry", f"timeout retry {attempt+1}/{retries-1} wait {wait}s")
            print(f"[timeout] {url} — retry in {wait}s ({type(exc).__name__})", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {retries} retries")


def fetch_pnl(session: requests.Session, alpha_id: str) -> list[float]:
    """Fetch cumulative PnL recordset; tolerate list/dict schema.properties.

    Automatically re-authenticates if the session has expired.
    """
    try:
        resp = get_with_retry(
            session,
            f"{API_BASE}/alphas/{alpha_id}/recordsets/pnl",
        )
    except Exception:
        return []
    if resp.status_code != 200 or not resp.text.strip():
        return []
    try:
        data = resp.json()
    except Exception:
        return []

    schema = data.get("schema", {})
    props = schema.get("properties", [])
    if isinstance(props, list):
        date_idx = next((i for i, p in enumerate(props) if p.get("name", "").lower() == "date"), 0)
        pnl_idx = next(
            (i for i, p in enumerate(props) if p.get("name", "").lower() in ("pnl", "cum_pnl", "returns", "ret")),
            1,
        )
    else:
        date_idx = next((v["index"] for k, v in props.items() if k.lower() == "date"), 0)
        pnl_idx = next(
            (v["index"] for k, v in props.items() if k.lower() in ("pnl", "cum_pnl", "returns", "ret")),
            1,
        )

    records = sorted(data.get("records", []), key=lambda r: r[date_idx])
    out: list[float] = []
    for row in records:
        rec = row[0] if isinstance(row, list) and len(row) == 1 and isinstance(row[0], list) else row
        try:
            out.append(float(rec[pnl_idx]))
        except Exception:
            continue
    return out


def fetch_user_alphas(session: requests.Session, limit: int = 100) -> list[dict]:
    """Fetch all user alphas with pagination."""
    def is_pagination_boundary_response(resp: requests.Response) -> bool:
        """Detect API-level pagination limits that signal a graceful stop.

        BRAIN returns several distinct 400 responses when offset leaves the
        accessible range:
          - ``"Invalid offset"`` (historical)
          - ``"Cannot display more than the first 1,000 alphas"`` (hard cap)
        Any of these, when we have already fetched at least one page, should
        be treated as "you've reached the end of what's available", not as
        a fatal error.
        """
        if resp.status_code != 400:
            return False
        text = (getattr(resp, "text", "") or "").lower()
        if "invalid offset" in text:
            return True
        if "cannot display more" in text:
            return True
        if "display more than the first" in text:
            return True
        try:
            payload = resp.json()
        except Exception:
            return False

        def _match(value: Any) -> bool:
            if isinstance(value, str):
                low = value.lower()
                return any(
                    keyword in low
                    for keyword in ("invalid offset", "cannot display more", "display more than")
                )
            if isinstance(value, dict):
                return any(_match(v) for v in value.values())
            if isinstance(value, list):
                return any(_match(v) for v in value)
            return False

        return _match(payload)

    all_alphas: list[dict] = []
    seen_ids: set[str] = set()
    offset = 0
    fetched_any_page = False
    while True:
        resp = get_with_retry(
            session,
            f"{API_BASE}/users/self/alphas",
            params={"limit": limit, "offset": offset},
        )
        if resp.status_code != 200:
            if fetched_any_page and is_pagination_boundary_response(resp):
                break
            raise RuntimeError(f"Failed to fetch alphas: {resp.status_code} {resp.text}")
        data = resp.json()
        batch = data.get("results", data.get("alphas", []))
        if not batch:
            break
        new_count = 0
        for alpha in batch:
            alpha_id = alpha.get("id")
            if alpha_id and alpha_id in seen_ids:
                continue
            if alpha_id:
                seen_ids.add(alpha_id)
            all_alphas.append(alpha)
            new_count += 1
        fetched_any_page = True
        if len(batch) < limit:
            break
        if new_count == 0:
            break
        offset += limit
        # Report fleet progress so the panel shows something useful
        if offset % 500 == 0 or offset == limit:
            emit_stage_progress("fetch_alphas", f"fetched {len(all_alphas)} alphas offset={offset}")
        time.sleep(2)  # BRAIN community standard: 60s between batches, 2s between pages
    return all_alphas


def daily_returns(cum_pnl: list[float]) -> list[float]:
    return [cum_pnl[i + 1] - cum_pnl[i] for i in range(len(cum_pnl) - 1)]


def load_alpha_db() -> dict[str, Any]:
    if ALPHA_DB_PATH.exists():
        return json.loads(ALPHA_DB_PATH.read_text(encoding="utf-8"))
    return {"alphas": {}, "last_update": None, "version": 1}


def save_alpha_db(db: dict[str, Any]) -> None:
    """Atomic write via tmp + replace with retry on transient Windows locks.

    On Windows, alpha_db.json may be opened by a concurrent reader (e.g.
    panel_app refreshing state).  A naive tmp.replace() raises
    PermissionError.  We retry up to 5 times with exponential backoff, and
    fall back to direct overwrite if every retry fails.
    """
    tmp = ALPHA_DB_PATH.with_suffix(".tmp")
    # Write the tmp file first
    for attempt in range(3):
        try:
            if tmp.exists():
                tmp.unlink()
            break
        except PermissionError:
            if attempt == 2:
                # tmp is stuck — give up on atomic and try direct overwrite
                ALPHA_DB_PATH.write_text(
                    json.dumps(db, indent=2, default=str), encoding="utf-8"
                )
                return
            time.sleep(0.5 * (attempt + 1))
    tmp.write_text(json.dumps(db, indent=2, default=str), encoding="utf-8")

    # Replace target with retry — handles Windows file lock contention
    for attempt in range(5):
        try:
            os.replace(tmp, ALPHA_DB_PATH)
            return
        except PermissionError as e:
            if attempt == 4:
                # Final fallback: try a different tmp suffix
                alt = ALPHA_DB_PATH.with_suffix(f".tmp.{os.getpid()}")
                try:
                    alt.write_text(json.dumps(db, indent=2, default=str), encoding="utf-8")
                    os.replace(alt, ALPHA_DB_PATH)
                    return
                except Exception:
                    raise e
            time.sleep(0.5 * (2 ** attempt))


def compute_alpha_fingerprint(alpha: dict) -> dict[str, Any]:
    """Stable snapshot of an alpha that we can compare across runs."""
    is_ = alpha.get("is", {}) if isinstance(alpha.get("is"), dict) else {}
    expr_obj = alpha.get("regular", alpha.get("expression", {}))
    expr = expr_obj.get("code") if isinstance(expr_obj, dict) else str(expr_obj)
    settings = alpha.get("settings", {}) or {}
    return {
        "status": alpha.get("status"),
        "expression": expr,
        "settings": settings,
        "region": settings.get("region", "USA"),
        "universe": settings.get("universe", "TOP3000"),
        "delay": settings.get("delay", 1),
        "sharpe": is_.get("sharpe"),
        "fitness": is_.get("fitness"),
        "returns": is_.get("returns"),
        "turnover": is_.get("turnover"),
        "drawdown": is_.get("drawdown"),
        "margin": is_.get("margin"),
        "long_count": is_.get("longCount"),
        "short_count": is_.get("shortCount"),
    }


def classify_alpha(expr: str, settings: dict[str, Any] | None = None) -> str:
    """Classify alpha into signal family based on data fields and construction patterns.

    Uses the WQ BRAIN field taxonomy (fundamental / analyst / news / pv / option /
    model / socialmedia) plus operator patterns documented in SKILL.md Section 2.
    Returns hyphenated tokens (e.g. ``"analyst-fundamental"``) or ``"other"`` when
    no recognisable cluster is found.

    Classification rules (in priority order):
    * **analyst**  – expression references ``est_*``, ``anl*``, ``consensus``,
      ``recommendation`` fields; or uses ``group_rank`` with INDUSTRY/SUBINDUSTRY
      neutralisation at decay 0-4.
    * **fundamental** – expression references ``book_*``, ``operating_*``,
      ``cash_flow*``, ``free_cash_*``, ``roe``, ``roa``, ``gross_``, ``ebitda``,
      ``net_income``, ``revenue``, ``dividend``, ``equity``, ``assets``,
      ``liabilities``, ``sales``, ``eps`` (standalone, not ``est_eps``);
      or uses ``group_rank`` with SUBINDUSTRY neutralisation at decay=0.
    * **technical** – expression references ``close``, ``open``, ``high``, ``low``,
      ``volume``, ``vwap``, ``adv``, ``returns``, ``turnover`` as core price/volume
      tokens; or uses ``trade_when``, ``ts_mean``, ``ts_std_dev``, ``ts_delta``,
      ``ts_rank`` windows >= 10.
    * **sentiment** – expression references ``sentiment``, ``buzz``, ``scl*``,
      ``social`` fields; or explicit ``nanHandling`` settings.
    * **news** – expression references ``event*``, ``news*``, ``mws*`` fields.
    * **option** – expression references ``option*``, ``implied*``, ``put_*``,
      ``call_*`` fields.
    * **model** – expression references ``model*``, ``mws*`` model-type fields
      (machine-learning or WS-derived indicators).

    If a token is not matched, ``family`` is appended when SKILL.md Section 2
    provides operator-level hints (e.g. ``group_rank`` without identifiable field
    category → ``fundamental`` as the most common group_rank use case).
    """
    expr_lower = expr.lower()
    tokens: list[str] = []

    # ── Field-level classification ───────────────────────────────────
    # Analyst: consensus / estimate fields
    # BRAIN prefix evidence:
    #   anl*: 928 fields (anl4_*) — the dominant analyst prefix
    #   est_*: 28 fields — explicit estimate fields
    #   min/max are overlapping prefixes (also appear in other categories);
    #   only "anl" and "est_" are reliable single-category signals.
    # NOTE: "_sentiment" removed — it is a false-positive magnet (catches
    #   news_sentiment, social_sentiment) and "anl" already catches anl*_sentiment.
    if any(f in expr_lower for f in [
        "est_eps", "est_fcf", "est_revenue", "est_ebitda", "est_ptp",
        "est_",  # catch-all for est_* fields
        "anl",   # analyst fields (e.g. anl4_*, anl46_sentiment)
        "consensus",
        "recommendation",
    ]):
        tokens.append("analyst")

    # Fundamental: balance sheet / income statement / cash flow fields
    # BRAIN prefix evidence (from references/wq_usa_top3000_delay1_data_fields.json):
    #   fnd*: 960+ fields (fnd6=838, fnd2=124) — the dominant fundamental prefix
    #   fn*:  194 fields — deprecated fundamental prefix kept for backward compat
    #   The remainder are ratio fields directly named (roe, ebitda, etc.).
    if any(f in expr_lower for f in [
        "fnd",       # catches fnd6_*, fnd2_*, fnd17_* (~960 fundamental fields)
        "book_", "operating_", "cash_flow", "free_cash",
        "roe", "roa", "gross_", "ebitda", "net_income",
        "revenue", "dividend", "equity", "assets", "liabilities",
        "sales", "total_debt", "current_ratio", "debt_to",
        "payout_ratio", "pe_ratio", "pb_ratio", "ps_ratio",
        "eps",  # standalone EPS (est_eps is caught by analyst above)
    ]):
        tokens.append("fundamental")

    # Technical / price-volume
    if any(f in expr_lower for f in [
        "close/open", "open/close", "vwap", "returns", "volume",
        "high + low", "high+low", "(close)", "(open)", "(high)",
        "(low)", "(volume)", "adv", "turnover",
        "close", "open", "high", "low",  # core price tokens
    ]):
        tokens.append("technical")

    # Sentiment / social
    if any(f in expr_lower for f in [
        "scl",       # BRAIN social media prefix (e.g. scl12_buzz)
        "snt",       # BRAIN social sentiment prefix (e.g. snt12_sentiment)
        "_buzz",     # social buzz indicator
        "sentiment",
        "social",
    ]):
        tokens.append("sentiment")

    # News / event-driven
    # BRAIN prefix evidence:
    #   nws*: 247 fields — the dominant news prefix (nws12_*)
    #   news*: 76 fields — secondary news prefix
    #   event*: ~80 fields — event-driven indicators
    #   mws* is explicitly NOT news (it is BRAIN "model" category, 40 fields).
    if any(f in expr_lower for f in [
        "nws",       # nws12_* news fields (247 of 996)
        "event",     # event-driven indicators
        "news",      # news-prefixed fields (76 of 996)
    ]):
        tokens.append("news")

    # Option
    if any(f in expr_lower for f in [
        "option", "implied", "pcr", "put_", "call_",
    ]):
        tokens.append("option")

    # ── Operator-level classification (when no field tokens matched) ──
    if not tokens:
        if any(op in expr_lower for op in ["group_rank", "group_neutralize"]):
            tokens.append("fundamental")  # group_rank most common in financial contexts
        elif any(op in expr_lower for op in ["trade_when"]):
            tokens.append("technical")    # trade_when is timing/volume-based
        elif any(op in expr_lower for op in ["ts_rank", "ts_mean", "ts_std_dev", "ts_delta",
                                              "ts_min", "ts_max", "ts_sum"]):
            tokens.append("technical")    # time-series ops are technical by default
        elif any(op in expr_lower for op in ["rank", "zscore"]):
            # Pure rank/zscore without identifiable fields → inspect settings
            pass

    # ── Settings-level hints ─────────────────────────────────────────
    if settings:
        neut = (settings.get("neutralization") or "").upper()
        decay = settings.get("decay", 0)
        if not tokens:
            if neut == "SUBINDUSTRY" and decay == 0:
                tokens.append("fundamental")
            elif neut in ("INDUSTRY", "SUBINDUSTRY") and 1 <= decay <= 4:
                tokens.append("analyst")
            elif decay >= 10:
                tokens.append("technical")

    return "-".join(tokens) if tokens else "other"


def correlation_with_existing(
    new_pnl: list[float], db: dict[str, Any], min_records: int = 50
) -> list[dict[str, Any]]:
    """Compute daily-return correlation of a new alpha against all ACTIVE alphas in DB."""
    if len(new_pnl) < min_records + 1:
        return []
    new_ret = np.array(daily_returns(new_pnl))
    results: list[dict[str, Any]] = []
    for old_id, old in db.get("alphas", {}).items():
        if old.get("status") != "ACTIVE" or not old.get("pnl"):
            continue
        old_ret = np.array(daily_returns(old["pnl"]))
        if len(new_ret) != len(old_ret):
            continue
        corr = float(np.corrcoef(new_ret, old_ret)[0, 1])
        results.append({"alpha_id": old_id, "corr": corr, "sharpe": old.get("sharpe"), "fitness": old.get("fitness")})
    results.sort(key=lambda x: abs(x["corr"]), reverse=True)
    return results


def generate_lesson(fp: dict[str, Any], top_corr: list[dict[str, Any]]) -> str:
    """Generate a one-line lesson from this alpha."""
    if fp["fitness"] is None:
        metric_note = "模拟失败或数据缺失"
    elif fp["fitness"] >= 1.5 and fp["turnover"] is not None and fp["turnover"] <= 0.15:
        metric_note = "高 Fitness 低换手，优秀候选"
    elif fp["fitness"] >= 1.1 and fp["turnover"] is not None and fp["turnover"] <= 0.20:
        metric_note = "满足基础提交门槛"
    elif fp["turnover"] is not None and fp["turnover"] > 0.35:
        metric_note = "换手偏高，需增大 decay 或混合稳定信号"
    else:
        metric_note = "指标一般，需继续优化"

    if not top_corr:
        corr_note = "暂无 ACTIVE alpha 可比相关"
    elif abs(top_corr[0]["corr"]) >= 0.7:
        corr_note = f"与 {top_corr[0]['alpha_id']} 高度相关 ({top_corr[0]['corr']:.2f})，需换信号簇"
    elif abs(top_corr[0]["corr"]) >= 0.5:
        corr_note = f"与 {top_corr[0]['alpha_id']} 中等相关 ({top_corr[0]['corr']:.2f})，谨慎提交"
    else:
        corr_note = f"与现有 ACTIVE alpha 低相关 ({top_corr[0]['corr']:.2f})，分散价值较高"

    return f"{metric_note}；{corr_note}"


def truncate_expr(expr: str, max_len: int = 120) -> str:
    expr = expr or ""
    lines = expr.strip().splitlines()
    first = lines[0].strip() if lines else ""
    if len(first) > max_len:
        first = first[: max_len - 3] + "..."
    return first


def build_bulk_summary(alphas: list[dict], active_correlations: dict[str, list[dict[str, Any]]]) -> str:
    """Build a compact summary for the first (bulk) run."""
    from collections import Counter

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(alphas)
    active = [a for a in alphas if a.get("status") == "ACTIVE"]
    unsubmitted = [a for a in alphas if a.get("status") != "ACTIVE"]
    families = Counter(classify_alpha(a.get("regular", {}).get("code", "")) for a in alphas)

    top_active = sorted(active, key=lambda a: (a.get("is", {}).get("fitness") or 0), reverse=True)[:5]
    failures = [a for a in alphas if a.get("is", {}).get("fitness") is not None and a.get("is", {}).get("fitness") < 0.5]
    high_to = [a for a in alphas if a.get("is", {}).get("turnover") is not None and a.get("is", {}).get("turnover") > 0.50]

    lines = [
        f"\n### {now} — 批量初始化快照\n",
        f"- 总 alpha：{total} | ACTIVE：{len(active)} | 非 ACTIVE：{len(unsubmitted)}",
        f"- 信号簇分布：{dict(families.most_common(8))}",
        "",
        "**ACTIVE 高 Fitness Top 5**：",
    ]
    for a in top_active:
        is_ = a.get("is", {})
        expr = truncate_expr(a.get("regular", {}).get("code", ""))
        sharpe = is_.get("sharpe") or 0.0
        fitness = is_.get("fitness") or 0.0
        turnover = is_.get("turnover") or 1.0
        lines.append(
            f"- `{a['id']}` ({classify_alpha(a.get('regular', {}).get('code', ''))}): "
            f"Sharpe={sharpe:.2f}, Fitness={fitness:.2f}, TO={turnover:.3f} — `{expr}`"
        )

    if active_correlations:
        high_corr_pairs = []
        ids = sorted(active_correlations.keys())
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                corr = next((c["corr"] for c in active_correlations[a] if c["alpha_id"] == b), None)
                if corr is None:
                    corr = next((c["corr"] for c in active_correlations[b] if c["alpha_id"] == a), 0.0)
                if abs(corr) >= 0.7:
                    high_corr_pairs.append((a, b, corr))
        if high_corr_pairs:
            lines.extend(["", "**ACTIVE 中日收益高相关对（≥ 0.7）**："])
            for a, b, c in high_corr_pairs[:10]:
                lines.append(f"- `{a}` vs `{b}`: {c:.3f}")
        else:
            lines.extend(["", "**ACTIVE 中日收益高相关对**：无 ≥ 0.7 的对（或 PnL 不足）"])

    if failures:
        lines.extend(["", f"**明显失效信号（Fitness < 0.5，共 {len(failures)} 个）**："])
        families_fail = Counter(classify_alpha(a.get("regular", {}).get("code", "")) for a in failures)
        lines.append(f"- 簇分布：{dict(families_fail.most_common(5))}")

    if high_to:
        lines.extend(["", f"**高换手（TO > 50%，共 {len(high_to)} 个）**："])
        families_to = Counter(classify_alpha(a.get("regular", {}).get("code", "")) for a in high_to)
        lines.append(f"- 簇分布：{dict(families_to.most_common(5))}")

    lines.append("\n---\n")
    return "\n".join(lines)


def build_incremental_report(entries: list[dict[str, Any]]) -> str:
    """Build per-alpha markdown for incremental updates."""
    if not entries:
        return ""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"\n### {now}\n"]
    for e in entries:
        if e.get("event") == "status_or_metric_changed":
            lines.append(
                f"- **{e['alpha_id']}** 状态变化：{e['old_status']} → {e['new_status']}；"
                f"Sharpe={e['sharpe']}, Fitness={e['fitness']}, TO={e['turnover']}。{e['lesson']}"
            )
        else:
            lines.append(
                f"- **{e['alpha_id']}** ({e['status']}, {e['family']}): "
                f"Sharpe={e['sharpe']}, Fitness={e['fitness']}, TO={e['turnover']}, DD={e['drawdown']}。"
                f"{e['lesson']}"
            )
            if e["top_corr"]:
                corr_strs = [f"{c['alpha_id']}({c['corr']:+.2f})" for c in e["top_corr"]]
                lines.append(f"  - 相关：{', '.join(corr_strs)}")
            expr = truncate_expr(e["expression"])
            if expr:
                lines.append(f"  - 表达式：`{expr}`")
    lines.append("\n---\n")
    return "\n".join(lines)


def append_to_skill(snippet: str) -> None:
    """Append snippet to the end of SKILL.md (Section 12 is the last section)."""
    if not SKILL_PATH.exists():
        raise FileNotFoundError(f"SKILL.md not found at {SKILL_PATH}")
    content = SKILL_PATH.read_text(encoding="utf-8")
    marker = "## 12. 实证记录（自动更新）"
    if marker not in content:
        content += f"\n\n{marker}\n\n{snippet}"
    else:
        if not content.endswith("\n"):
            content += "\n"
        content += snippet + "\n"
    SKILL_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Generation Guidance — bridges evolve_skill (Organize) → candidate_generator (Act)
# ---------------------------------------------------------------------------
_EXHAUSTION_CONFIRMED_MIN_OCCURRENCES = 5       # 5+ 次才判 confirmed
_EXHAUSTION_SUSPECTED_MIN_OCCURRENCES = 3       # 3+ 次判 suspected
_EXHAUSTION_MEDIAN_SHARPE_CEILING = 1.0         # median Sharpe < 1.0 才算枯竭
_GUIDANCE_VALID_CYCLES = 2                      # guidance 有效期（cycle 数）


def _extract_expression_core(expr: str) -> str:
    """Extract the structural core of an expression for pattern matching.

    Strips numeric literals and truncates at first major structural boundary,
    producing a fingerprint suitable for exhausted-pattern detection without
    being sensitive to parameter changes.
    """
    import re
    core = re.sub(r'\b\d+\b', '*', expr)
    # Truncate at the first top-level operator boundary
    boundary = None
    depth = 0
    for i, ch in enumerate(core):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0 and ch == ',':
            boundary = i
            break
    if boundary is not None:
        core = core[:boundary]
    return core[:120] if len(core) > 120 else core


def _write_generation_guidance(
    db: dict,
    all_alphas: list[dict],
    entries: list[dict[str, Any]] | None,
    cycle_count: int = 0,
) -> None:
    """Write ``generation_guidance.json`` from the latest empirical data.

    Called exclusively inside the ``--apply`` code path, so it only writes
    when the operator has reviewed and committed the evolutionary update.
    The file is intentionally not git-tracked (like alpha_db.json).

    Design invariants:
    - Degradation-first: any field that fails to compute is omitted from the
      output rather than crashing the function.  The downstream reader must
      treat missing fields as "no guidance available".
    - The ``source_cycle`` field ties the guidance to a specific runtime
      cycle so stale-guidance detection is trivial.
    - Exhaustion levels use the three-tier system (confirmed / suspected /
      watch) defined in the final design doc.  Only *confirmed* patterns are
      eligible for the ``block_systematic_scan`` action.
    """
    alphas = db.get("alphas", {})
    if not alphas:
        return

    # ── 1. Signal cluster statistics ────────────────────────────────
    cluster_buckets: dict[str, list[tuple[float, float, float]]] = {}
    for aid, a in alphas.items():
        expr = a.get("expression", "")
        if not expr:
            continue
        # Compute cluster on-the-fly using the current classifier, NOT
        # the stored "family" field which may be stale from a previous
        # (less accurate) version of classify_alpha.
        settings = a.get("settings")
        cluster = classify_alpha(expr, settings).split("-")[0] or "other"
        sharpe = a.get("sharpe") or 0.0
        fitness = a.get("fitness") or 0.0
        turnover = a.get("turnover") or 1.0
        if cluster not in cluster_buckets:
            cluster_buckets[cluster] = []
        cluster_buckets[cluster].append((sharpe, fitness, turnover))

    cluster_stats: dict[str, dict[str, float]] = {}
    for c, vals in cluster_buckets.items():
        if not vals:
            continue
        sharpe_vals = sorted(v[0] for v in vals)
        fitness_vals = sorted(v[1] for v in vals)
        n = len(sharpe_vals)
        cluster_stats[c] = {
            "count": n,
            "sharpe_median": sharpe_vals[n // 2],
            "sharpe_p75": sharpe_vals[int(n * 0.75)] if n >= 4 else sharpe_vals[-1],
            "fitness_median": fitness_vals[n // 2],
        }

    # ── 2. Top parents (ACTIVE only) ─────────────────────────────────
    active = [
        {"alpha_id": aid, **a}
        for aid, a in alphas.items()
        if a.get("status") == "ACTIVE"
    ]
    active.sort(key=lambda a: a.get("fitness", 0), reverse=True)
    top_parents = active[:20]

    # ── 3. UNSUBMITTED high-potential pool ───────────────────────────
    unsubmitted_high: list[dict[str, Any]] = []
    for aid, a in alphas.items():
        status = a.get("status", "").upper()
        if status not in ("UNSUBMITTED", "PENDING"):
            continue
        if (a.get("fitness") or 0) < 1.0:
            continue
        # Resolve region/universe from top-level fields (new records) or
        # from the nested settings dict (legacy records written before the
        # compute_alpha_fingerprint region fix).
        region = a.get("region")
        universe = a.get("universe")
        if not region or not universe:
            s = a.get("settings")
            if isinstance(s, dict):
                region = region or s.get("region")
                universe = universe or s.get("universe")
        unsubmitted_high.append({
            "alpha_id": aid,
            "fitness": a.get("fitness"),
            "sharpe": a.get("sharpe"),
            "cluster": classify_alpha(a.get("expression", ""), a.get("settings")).split("-")[0] or "other",
            "region": region or "?",
            "universe": universe or "?",
        })
    # Region-aware selection: instead of pure fitness-sorted top 15
    # (which lets a single region like IND/F=6.74 monopolise every slot),
    # group by region and round-robin so EUR/ASI/CHN/GLB each get
    # representation.
    region_pools: dict[str, list[dict[str, Any]]] = {}
    for entry in unsubmitted_high:
        r = entry.get("region", "?")
        if r not in region_pools:
            region_pools[r] = []
        region_pools[r].append(entry)
    for pool in region_pools.values():
        pool.sort(key=lambda x: x.get("fitness", 0), reverse=True)

    unsubmitted_high = []
    region_names = sorted(region_pools.keys())
    while len(unsubmitted_high) < 15 and any(region_pools[r] for r in region_names):
        for r in region_names:
            if not region_pools[r]:
                continue
            if len(unsubmitted_high) >= 15:
                break
            unsubmitted_high.append(region_pools[r].pop(0))

    # ── 4. Exhausted patterns ────────────────────────────────────────
    # Previously this read from the incremental `entries` list, which
    # only contains *new BRAIN alphas* that appeared since the last
    # evolve_skill run.  When the account has a stable set of 1000
    # alphas (BRAIN API cap), entries is always empty and exhausted
    # detection never triggers.
    #
    # Read from candidate_submit_results.json instead — it contains the
    # actual evaluation history (45+ records) from the production
    # pipeline: expression, fitness, sharpe, rejection reason.
    exhausted: list[dict[str, Any]] = []
    submit_results_path = SKILL_DIR / "candidate_submit_results.json"
    if submit_results_path.exists():
        from collections import defaultdict as _dd2
        try:
            submit_results = json.loads(submit_results_path.read_text(encoding="utf-8"))
        except Exception:
            submit_results = []

        pattern_records: dict[str, list[float]] = _dd2(list)
        for r in submit_results:
            if not isinstance(r, dict):
                continue
            # Only count entries that were actually evaluated (have metrics
            # or a clear rejection reason), not transport errors.
            sub = r.get("submission", {})
            if isinstance(sub, dict) and sub.get("reason") == "metrics_threshold":
                expr = r.get("candidate", {}).get("expression", "")
            else:
                continue
            if not expr:
                continue
            core = _extract_expression_core(expr)
            sim = r.get("sim", {}) if isinstance(r.get("sim"), dict) else {}
            metrics = r.get("metrics", {}) if isinstance(r.get("metrics"), dict) else {}
            is_ = metrics.get("is", sim.get("sim_data", {}).get("is", {})) if isinstance(metrics, dict) else {}
            sharpe = is_.get("sharpe", 0) if isinstance(is_, dict) else 0
            pattern_records[core].append(sharpe or 0)

        for core, sharpe_list in pattern_records.items():
            n = len(sharpe_list)
            if n < _EXHAUSTION_SUSPECTED_MIN_OCCURRENCES:
                continue
            median_sharpe = sorted(sharpe_list)[n // 2]
            if median_sharpe >= _EXHAUSTION_MEDIAN_SHARPE_CEILING:
                continue
            level = "confirmed" if n >= _EXHAUSTION_CONFIRMED_MIN_OCCURRENCES else "suspected"
            exhausted.append({
                "pattern": core,
                "occurrences": n,
                "median_sharpe": round(median_sharpe, 2),
                "exhaustion_level": level,
                "action": "block_systematic_scan" if level == "confirmed" else "downgrade_quota",
            })

    # ── 4b. E block: BRAIN IS feedback bias ──────────────────────────
    # Learn from REAL in-sample signal: every COMPLETE simulation returns
    # is_metrics (sharpe/fitness/turnover), which is the only reliable ground
    # truth (AlphaBench, ICLR 2026).  We aggregate per-feature quality so the
    # NEXT generation is biased toward what BRAIN actually scored high.  This
    # is the correct feedback path — we do NOT relax the submission gate to
    # "learn"; the user wants HIGH-STANDARD factors, and quality is raised by
    # learning from real IS, not by submitting floor-level alphas.
    feedback_bias: dict = {"available": False, "n_samples": 0}
    if submit_results_path.exists():
        try:
            from core.infrastructure.brain_feedback import build_feedback_bias
            feedback_bias = build_feedback_bias(submit_results_path)
        except Exception:  # pragma: no cover - degradation-first
            feedback_bias = {"available": False, "n_samples": 0}

    # ── 5. Write (atomic, with OSError guard) ──────────────────────
    guidance = {
        "version": "qf.guidance.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cycle": cycle_count,
        "valid_until_cycle": cycle_count + _GUIDANCE_VALID_CYCLES,
        "parent_pool": {
            "active_top20": [
                {
                    "alpha_id": a["alpha_id"],
                    "cluster": classify_alpha(a.get("expression", ""), a.get("settings")).split("-")[0] or "other",
                    "fitness": a.get("fitness"),
                    "sharpe": a.get("sharpe"),
                    "turnover": a.get("turnover"),
                    "region": a.get("region", "USA"),
                    "universe": a.get("universe", "TOP3000"),
                }
                for a in top_parents
            ],
            "unsubmitted_high_potential": unsubmitted_high,
        },
        "cluster_stats": cluster_stats,
        "exhausted_patterns": exhausted,
        "feedback_bias": feedback_bias,
    }
    tmp = GUIDANCE_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(guidance, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        tmp.replace(GUIDANCE_PATH)
    except OSError:
        # Disk full or permissions — guidance is advisory; silently skip.
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Evolve WQ Alpha Research SKILL with new empirical data.")
    parser.add_argument("--apply", action="store_true", help="Automatically append the generated snippet to SKILL.md")
    args = parser.parse_args()

    session = create_session()
    print("auth ok", flush=True)

    db = load_alpha_db()
    known_ids = set(db.get("alphas", {}).keys())
    is_first_run = len(known_ids) == 0

    emit_stage_progress("fetch_alphas", "starting")
    all_alphas = fetch_user_alphas(session)
    print(f"fetched {len(all_alphas)} alphas, known={len(known_ids)}", flush=True)

    # ── Refresh pass: pull IS data for BRAIN-ACTIVE alphas the local DB
    #    is blind to (submitted via web UI, status changed, etc.).
    emit_stage_progress("refresh_missing_active", "checking")
    braim_active = {a.get("id") for a in all_alphas if a.get("status") == "ACTIVE"}
    blind = 0
    for aid in braim_active:
        entry = db["alphas"].get(aid, {})
        if entry.get("fitness") is None or entry.get("sharpe") is None:
            try:
                resp = session.get(f"{API_BASE}/alphas/{aid}", timeout=(10, 15))
                if resp.status_code == 200:
                    full = resp.json()
                    ism = full.get("is", {}) or {}
                    db["alphas"][aid] = {
                        "expression": (full.get("regular") or {}).get("code", entry.get("expression", "")),
                        "status": full.get("status", entry.get("status")),
                        "sharpe": ism.get("sharpe", 0),
                        "fitness": ism.get("fitness", 0),
                        "turnover": ism.get("turnover", 1),
                        "pnl": entry.get("pnl", []),
                    }
                    blind += 1
                    if blind % 10 == 0:
                        emit_stage_progress("refresh_missing_active", f"refreshed {blind}")
                    time.sleep(0.5)
            except Exception:
                pass
    if blind:
        print(f"  refreshed IS data for {blind} previously blind ACTIVE alphas", flush=True)
        save_alpha_db(db)
    emit_stage_progress("fetch_alphas", f"fetched {len(all_alphas)}, refreshed {blind} blind")

    new_alphas: list[dict] = []
    changed_alphas: list[tuple[dict, dict]] = []

    for alpha in all_alphas:
        aid = alpha.get("id")
        if not aid:
            continue
        fp = compute_alpha_fingerprint(alpha)

        if aid not in known_ids:
            new_alphas.append(alpha)
        else:
            old = db["alphas"][aid]
            if old.get("status") != fp["status"] or old.get("sharpe") != fp["sharpe"]:
                changed_alphas.append((old, {**fp, "alpha_id": aid}))

    # ------------------------------------------------------------------
    # Preview mode: compute snippet without mutating DB
    # ------------------------------------------------------------------
    if is_first_run:
        print("first run: building bulk snapshot...", flush=True)
        emit_stage_progress("bulk_snapshot", f"alphas={len(all_alphas)}")
        # Only fetch PnL for ACTIVE alphas — UNSUBMITTED ones have empty PnL
        # and waste API quota. This reduces 9994 fetches to ~2-10 actual ones.
        active_alphas = [a for a in all_alphas if a.get("status") == "ACTIVE"]
        active_correlations: dict[str, list[dict[str, Any]]] = {}

        preview_db = {"alphas": {}}
        for idx, alpha in enumerate(all_alphas):
            aid = alpha.get("id")
            fp = compute_alpha_fingerprint(alpha)
            # Only fetch PnL for ACTIVE alphas (others return empty PnL anyway)
            if alpha.get("status") == "ACTIVE":
                pnl = fetch_pnl(session, aid)
            else:
                pnl = []
            preview_db["alphas"][aid] = {**fp, "pnl": pnl}
            emit_stage_progress("fetch_pnl", f"{idx + 1}/{len(all_alphas)}")
            if idx % 10 == 0:
                print(f"  fetched {idx + 1}/{len(all_alphas)} PnLs", flush=True)
            time.sleep(0.6)  # 0.3s 触发 429，提升到 0.6s

        active_ids = [a.get("id") for a in active_alphas if a.get("id")]
        emit_stage_progress("build_correlation", f"active={len(active_ids)}")
        for aid in active_ids:
            pnl = preview_db["alphas"][aid].get("pnl", [])
            active_correlations[aid] = correlation_with_existing(pnl, preview_db)

        snippet = build_bulk_summary(all_alphas, active_correlations)

        if args.apply:
            db["alphas"] = preview_db["alphas"]
    else:
        # ------------------------------------------------------------------
        # Incremental run: per-alpha entries for new/changed only
        # ------------------------------------------------------------------
        print(f"incremental: {len(new_alphas)} new, {len(changed_alphas)} changed", flush=True)
        emit_stage_progress("incremental_scan", f"new={len(new_alphas)},changed={len(changed_alphas)}")
        entries: list[dict[str, Any]] = []

        for idx, alpha in enumerate(new_alphas, start=1):
            aid = alpha.get("id")
            fp = compute_alpha_fingerprint(alpha)
            pnl = fetch_pnl(session, aid)

            top_corr = correlation_with_existing(pnl, db)
            lesson = generate_lesson(fp, top_corr)
            entries.append(
                {
                    "alpha_id": aid,
                    "status": fp["status"],
                    "family": classify_alpha(fp["expression"], fp.get("settings")).split("-")[0],
                    "sharpe": fp["sharpe"],
                    "fitness": fp["fitness"],
                    "turnover": fp["turnover"],
                    "drawdown": fp["drawdown"],
                    "expression": fp["expression"],
                    "top_corr": top_corr[:3],
                    "lesson": lesson,
                }
            )
            if args.apply:
                db["alphas"][aid] = {**fp, "pnl": pnl}
            print(f"  new: {aid} | sharpe={fp['sharpe']} | fitness={fp['fitness']} | to={fp['turnover']}")
            emit_stage_progress("fetch_pnl", f"{idx}/{len(new_alphas)}")
            time.sleep(0.6)  # 0.3s 触发 429，提升到 0.6s

        for old, new in changed_alphas:
            aid = new["alpha_id"]
            if aid in db["alphas"] and "pnl" in db["alphas"][aid]:
                new["pnl"] = db["alphas"][aid]["pnl"]
            entries.append(
                {
                    "alpha_id": aid,
                    "event": "status_or_metric_changed",
                    "old_status": old.get("status"),
                    "new_status": new["status"],
                    "sharpe": new["sharpe"],
                    "fitness": new["fitness"],
                    "turnover": new["turnover"],
                    "lesson": f"状态从 {old.get('status')} 变为 {new['status']}",
                }
            )
            if args.apply:
                db["alphas"][aid] = new
            print(f"  changed: {aid} | {old.get('status')} -> {new['status']}")

        snippet = build_incremental_report(entries)

    # ── Persist ──────────────────────────────────────────────────────
    # Two independent data sources feed guidance:
    #   (a) alpha_db — evolve_skill refreshes blind ACTIVE alphas and
    #       writes new/changed entries.
    #   (b) candidate_submit_results.json — written by candidate_submitter
    #       with the actual evaluation history.
    # Guidance MUST be regenerated every --apply cycle even when snippet
    # is empty (no new BRAIN alphas), because (b) changes independently
    # and drives exhausted_patterns + cluster_stats.
    if args.apply:
        db["evolution_round"] = db.get("evolution_round", 0) + 1
        db["last_update"] = datetime.now(timezone.utc).isoformat()
        save_alpha_db(db)

        if snippet.strip():
            append_to_skill(snippet)

        _write_generation_guidance(
            db, all_alphas,
            entries if not is_first_run else None,
            db["evolution_round"],
        )
        print(f"\nalpha_db.json updated: {len(db['alphas'])} alphas tracked.")
        print(f"generation_guidance.json written (round {db['evolution_round']})")
        if snippet.strip():
            print(f"Appended to {SKILL_PATH}")
        else:
            print("No new empirical findings — guidance refreshed from evaluation history.")

        return 0

    if not snippet.strip():
        print("\nNo new empirical findings to record.")
        return 0

    print("\n" + "=" * 60)
    print("PROPOSED SKILL.md APPEND SNIPPET")
    print("=" * 60)
    print(snippet)
    print("=" * 60)
    print("\nDry-run: SKILL.md and alpha_db.json were NOT modified. Use --apply to commit.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
