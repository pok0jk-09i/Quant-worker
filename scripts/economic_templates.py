"""Economic template library (P1-A block D) — pillar ① ECONOMIC GROUNDING.

Each template is a formulaic alpha skeleton with an explicit, literature-backed
economic hypothesis.  They are injected directly into the candidate pool as
FRESH seeds (not mutated from ghost parents), injecting real economic meaning
and cross-family diversity — the two pillars WorldQuant's own researchers cite
as the difference between passing and remixing (Kakushadze 101 Alphas: avg
pairwise corr 15.9%; Darren Li BRAIN Gold: PnL corr < 0.7 = real edge).

Research basis (top-tier, cross-validated 2026-08-02):
  * Kakushadze 101 Formulaic Alphas (arXiv:1601.00991) — every factor has a
    stated economic meaning; short-term reversal + value + low-vol dominate.
  * jglazar, WQ Intl Quant Championship (top 1.3% world) — real IS results:
      - (high+low)/2 - close          -> Sharpe 1.80 (price reversion)
      - -ts_zscore(EV/ebitda, 63)     -> Sharpe 2.00 (value/quality)
  * QuantGPT (ComeStart) — 3 BRAIN IS-PASS composites:
      - -rank(ts_av_diff(close,10)) + rank(debt/enterprise_value) Sharpe 1.77
      - -rank(ts_decay_linear(close/vwap,10))                   Sharpe 1.69
      - -rank(ts_decay_linear(returns*volume/adv20,5))          Sharpe 1.60
  * DeepWiki Alpha101 formula-pattern structures (volume / volatility /
    cross-sectional ranking templates).

All templates use ONLY timeout-safe, high-coverage MATRIX fields so they
compose cleanly with R3-C (no stall-prone fields) and the generator's
field-substitution / rank-wrap pipeline.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable


# ── Builders: each returns a RAW economic-signal expression ──────────────
# (generate_variants applies _safe_rank_wrap + field-sub + param sweep.)
# Lookback-bearing builders accept an optional ``lookback`` so tests can fuzz.

def build_mean_reversion_price() -> str:
    """Buy when price sits below its intraday average (mean reversion)."""
    return "(high + low) / 2 - close"


def build_short_term_reversal(lookback: int = 33) -> str:
    """Short-term reversal: yesterday's losers bounce (returns反转)."""
    return f"-ts_mean(returns, {lookback})"


def build_vwap_deviation_reversal(lookback: int = 10) -> str:
    """Price deviated below VWAP mean-reverts (情绪过度反应回归)."""
    return f"-ts_decay_linear(close / vwap, {lookback})"


def build_volume_price_reversal(lookback: int = 5) -> str:
    """Volume-weighted price move reversal (量价共振反转)."""
    return f"-ts_decay_linear(returns * volume / adv20, {lookback})"


def build_debt_momentum_composite() -> str:
    """Composite: price momentum reversal + valuation filter (多源低相关)."""
    return "-rank(ts_av_diff(close, 10)) + rank(debt / enterprise_value)"


def build_value_quality(lookback: int = 63) -> str:
    """Short richly-valued firms (value/quality, 基本面低频低换手)."""
    return f"-ts_zscore(enterprise_value / ebitda, {lookback})"


def build_liquidity_activity() -> str:
    """Trading-activity signal (流动性/活跃度)."""
    return "volume / adv20"


def build_low_volatility(lookback: int = 20) -> str:
    """Low-volatility anomaly (低波动溢价)."""
    return f"-ts_std_dev(returns, {lookback})"


# ── Registry ────────────────────────────────────────────────────────────
# OrderedDict keeps a stable family order for round-robin generation.
ECONOMIC_TEMPLATES: "OrderedDict[str, dict]" = OrderedDict([
    ("mean_reversion_price", {
        "build": build_mean_reversion_price,
        "hypothesis": "Mean reversion: price below intraday average tends to bounce.",
    }),
    ("short_term_reversal", {
        "build": build_short_term_reversal,
        "hypothesis": "Short-term reversal of recent returns (losers bounce).",
    }),
    ("vwap_deviation_reversal", {
        "build": build_vwap_deviation_reversal,
        "hypothesis": "Price below VWAP mean-reverts after sentiment overshoot.",
    }),
    ("volume_price_reversal", {
        "build": build_volume_price_reversal,
        "hypothesis": "Volume-weighted price-move reversal (volume-price resonance).",
    }),
    ("debt_momentum_composite", {
        "build": build_debt_momentum_composite,
        "hypothesis": "Composite: price momentum reversal + valuation filter (low-correlation).",
    }),
    ("value_quality", {
        "build": build_value_quality,
        "hypothesis": "Short richly-valued firms; fundamental data => low turnover.",
    }),
    ("liquidity_activity", {
        "build": build_liquidity_activity,
        "hypothesis": "Trading-activity / liquidity signal.",
    }),
    ("low_volatility", {
        "build": build_low_volatility,
        "hypothesis": "Low-volatility premium (betting against high-variance names).",
    }),
])


def iter_template_expressions():
    """Yield ``(family, expression, hypothesis)`` for all 8 templates.

    Each builder is invoked with its default lookback so callers get a
    ready-to-use, research-backed base expression.
    """
    for family, meta in ECONOMIC_TEMPLATES.items():
        builder: Callable[..., str] = meta["build"]
        yield family, builder(), meta["hypothesis"]
