"""Tests for the timeout-prone field guard (R3-C / R3-A).

Validates the data-derived blocklist logic against the empirical
TIMEOUT/COMPLETE findings.  The frozen ``TIMEOUT_PRONE_FIELDS`` is a SUPERSET
of every field ever observed to stall (T>=2, C==0): the original 14
analyst/pv13/fundamental fields from the 2026-08-01 cycle PLUS 5 cash-flow /
relative-return fields re-derived from the CURRENT candidate_submit_results.json
(free_cash_flow_per_share, net_profit_adjusted_value, op_cash_flow_median,
rel_ret_cust, rel_ret_part).  The guard is a PREVENTION artifact, so the frozen
set legitimately retains historical fields even after the guard suppresses them
from new results.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from core.infrastructure import timeout_field_guard as g

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS = REPO_ROOT / "candidate_submit_results.json"


# Representative 100%-stall fields (T>=2, C=0 in observed data).
STALL_FIELDS = [
    "net_income_total_2",
    "cap",
    "net_debt_reported_value",
    "research_development_expense_reported_value",
    "rel_ret_comp",
    "anl4_fs_guidances_advanced_af_nd_epsr_maxguidance",
    "anl4_fs_detail_estimate_1qf_v4_nd_sh_equity_median",
    "max_book_value_per_share_guidance_2",
    "max_gross_income_guidance_2",
    "pv13_ustomergraphrank_auth_rank",
    "pv13_ustomergraphrank_page_rank",
    "pv13_com_rk_au",
    "pv13_revere_zipcode",
    "pv13_ompetitorgraphrank_hub_rank",
    # re-derived from CURRENT candidate_submit_results.json (cash-flow /
    # relative-return fields, 100% stall in new data; were a hole before)
    "free_cash_flow_per_share",
    "net_profit_adjusted_value",
    "op_cash_flow_median",
    "rel_ret_cust",
    "rel_ret_part",
]

# Fields observed to COMPLETE without stalling (C>=1, T=0) -> must NOT be flagged.
# NOTE: rel_ret_part was historically safe but the CURRENT results file shows it
# stalling (T=4, C=0); it is now in STALL_FIELDS / TIMEOUT_PRONE_FIELDS.  The
# remaining entries have no timeout evidence in either dataset.
SAFE_FIELDS = [
    "rel_ret_all",
    "pv13_revere_city",
    "anl4_ptp_number",
    "anl4_fs_detail_estimate_1qf_v4_nd_cff_median",
    "anl4_fs_detail_estimate_1qf_v4_nd_cfi_mean",
]

# Shared field (T=4, C=3, rate 0.57) -> deliberately NOT in blocklist.
SHARED_FIELD = "pv13_com_page_rank"


class TestTimeoutFieldGuard(unittest.TestCase):
    def test_is_timeout_prone_flags_stall_fields(self):
        for f in STALL_FIELDS:
            expr = f"-ts_zscore({f})"
            with self.subTest(field=f):
                self.assertTrue(g.is_timeout_prone(expr), f"{f} should stall")
                self.assertIn(f, g.timeout_prone_fields_in(expr))

    def test_is_timeout_prone_clears_safe_fields(self):
        for f in SAFE_FIELDS:
            expr = f"-ts_zscore({f})"
            with self.subTest(field=f):
                self.assertFalse(g.is_timeout_prone(expr), f"{f} is safe")
                self.assertEqual(g.timeout_prone_fields_in(expr), [])

    def test_shared_field_not_flagged(self):
        expr = f"-ts_zscore({SHARED_FIELD})"
        self.assertFalse(g.is_timeout_prone(expr))
        self.assertNotIn(SHARED_FIELD, g.TIMEOUT_PRONE_FIELDS)

    def test_extract_fields_excludes_operators_and_kwargs(self):
        # Family B expression with a kwarg (std=4) and heavy operators.
        expr = (
            "trade_when(greater(ts_mean(ts_corr(pv13_com_page_rank,"
            "pv13_com_page_rank,5),3),0.85),"
            "zscore(log(winsorize(ts_backfill(net_income_total_2,120),"
            "std=4))),0)"
        )
        fields = g.extract_fields(expr)
        # operators / kwarg must be gone
        for banned in ("trade_when", "greater", "ts_mean", "ts_corr",
                       "zscore", "log", "winsorize", "ts_backfill", "std"):
            self.assertNotIn(banned, fields)
        # real fields must remain
        self.assertIn("pv13_com_page_rank", fields)
        self.assertIn("net_income_total_2", fields)

    def test_timeout_prone_fields_in_reports_all_matches(self):
        expr = f"rank({STALL_FIELDS[0]}) + rank({STALL_FIELDS[5]})"
        found = g.timeout_prone_fields_in(expr)
        self.assertEqual(set(found), {STALL_FIELDS[0], STALL_FIELDS[5]})

    def test_effective_blocklist_has_no_hole_on_real_data(self):
        if not RESULTS.exists():
            self.skipTest("candidate_submit_results.json not present")
        rebuilt = g.rebuild_timeout_blocklist(RESULTS)
        eff = g.effective_timeout_blocklist()
        # The EFFECTIVE blocklist (frozen core ∪ live data-derived set) must
        # cover every field the current data shows as 100%-stall.  Because the
        # live results file keeps drifting, a hand-maintained frozen list alone
        # would develop holes; the effective set is computed at runtime so this
        # invariant holds regardless of how the data evolves.
        self.assertTrue(
            rebuilt <= eff,
            "effective blocklist has a HOLE: data-derived stall fields not blocked",
        )
        # The curated prevention core is always part of the effective set.
        self.assertTrue(g.TIMEOUT_PRONE_FIELDS <= eff)
        # Safe + shared fields must stay out of the effective blocklist.
        for f in SAFE_FIELDS + [SHARED_FIELD]:
            self.assertNotIn(f, eff, f"{f} must not be blocklisted")
        # Observed stall set is evidence-based and non-empty.  Its exact size
        # drifts as new results accumulate; do not pin to a stale count.
        self.assertGreaterEqual(len(rebuilt), 1)

    def test_guard_blocks_every_data_derived_stall(self):
        # Drift-proof: whatever the live data shows as 100%-stall must be
        # actually blocked by the guard (effective blocklist has no hole in
        # practice).  Re-derived automatically as data evolves.
        if not RESULTS.exists():
            self.skipTest("candidate_submit_results.json not present")
        rebuilt = g.rebuild_timeout_blocklist(RESULTS)
        for f in rebuilt:
            with self.subTest(field=f):
                self.assertTrue(
                    g.is_timeout_prone(f"-ts_zscore({f})"),
                    f"{f} derived as 100%-stall but the guard did NOT block it",
                )

    def test_core_market_fields_never_blocked(self):
        # HARD INVARIANT: universally-covered market fields (price / volume /
        # microstructure) have 100% daily coverage, so BRAIN can NEVER stall on
        # them.  They must never be flagged as timeout-prone — even if the live
        # results file happens to contain a small-sample artifact (e.g. ``open``
        # appearing in 2 TIMEOUT records and 0 COMPLETE records).  A regression
        # here would silently break generation of valid factors like
        # ``ts_mean(open, 20)`` or ``adv20 / open``.
        for f in g.NEVER_BLOCK_CORE:
            with self.subTest(field=f):
                self.assertFalse(
                    g.is_timeout_prone(f"-ts_zscore({f})"),
                    f"core market field {f} must NEVER be blocklisted",
                )
                self.assertNotIn(f, g.timeout_prone_fields_in(f"-ts_zscore({f})"))

    def test_effective_blocklist_excludes_core_even_if_in_results(self):
        # Adversarial: feed the guard a results file where core market fields
        # (open, close) show a fake 100%-stall signal (T>=2, C==0).  The
        # effective blocklist must STILL exclude them — the whitelist wins over
        # the data-derived rebuild.  This is what prevents a sparse live-results
        # slice from poisoning generation.
        import json
        import tempfile

        synthetic = [
            {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_mean(open, 20)"}},
            {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_mean(open, 20)"}},
            {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_zscore(close)"}},
            {"sim": {"status": "TIMEOUT"}, "candidate": {"expression": "ts_zscore(close)"}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(synthetic, fh)
            tmp = fh.name
        try:
            rebuilt = g.rebuild_timeout_blocklist(tmp)
            eff = g.effective_timeout_blocklist(tmp)
            self.assertNotIn("open", rebuilt, "whitelist must exclude core field from rebuild")
            self.assertNotIn("close", rebuilt, "whitelist must exclude core field from rebuild")
            self.assertNotIn("open", eff, "effective blocklist must never block core field")
            self.assertNotIn("close", eff, "effective blocklist must never block core field")
            # And the guard must clear expressions using them.
            self.assertFalse(g.is_timeout_prone("ts_mean(open, 20)"))
            self.assertFalse(g.is_timeout_prone("rank(-ts_decay_linear(adv20 / open, 10))"))
        finally:
            Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
