"""Unit tests for Quant worker core infrastructure.

Run with:
    python -m pytest core/infrastructure/tests/   # or
    python -m unittest discover -s core/infrastructure/tests

All tests are offline: they mock the network and the import system, so
they prove the *logic* (breaker state machine, contract detection, submit
gate, retry classification) without touching BRAIN.
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from core.infrastructure import circuit_breaker as cb  # noqa: E402
from core.infrastructure import runtime_contract as rc  # noqa: E402
from core.infrastructure import submit_gate as sg  # noqa: E402
from core.infrastructure import resilient_http as rh  # noqa: E402


class TestCircuitBreaker(unittest.TestCase):
    def test_closed_until_threshold(self):
        b = cb.CircuitBreaker("s", cb.CircuitBreakerConfig(
            failure_threshold=3, success_threshold=1, window_seconds=60, cooldown_seconds=0.01))
        # 2 failures: still CLOSED
        for _ in range(2):
            with self.assertRaises(ValueError):
                b.call(lambda: (_ for _ in ()).throw(ValueError()))
        self.assertEqual(b.state, cb.BreakerState.CLOSED)
        # 3rd failure trips OPEN
        with self.assertRaises(ValueError):
            b.call(lambda: (_ for _ in ()).throw(ValueError()))
        self.assertEqual(b.state, cb.BreakerState.OPEN)

    def test_open_rejects_then_half_open_then_closes(self):
        b = cb.CircuitBreaker("s", cb.CircuitBreakerConfig(
            failure_threshold=1, success_threshold=1, window_seconds=60, cooldown_seconds=1.0))
        with self.assertRaises(RuntimeError):
            b.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(b.state, cb.BreakerState.OPEN)
        # OPEN rejects immediately (no call to func)
        called = {"n": 0}
        with self.assertRaises(cb.CircuitBreakerOpen):
            b.call(lambda: called.__setitem__("n", 1))
        self.assertEqual(called["n"], 0)
        # after cooldown -> HALF_OPEN; success closes
        import time as _t
        _t.sleep(1.05)
        self.assertEqual(b.state, cb.BreakerState.HALF_OPEN)
        self.assertEqual(b.call(lambda: 42), 42)
        self.assertEqual(b.state, cb.BreakerState.CLOSED)

    def test_on_open_path(self):
        b = cb.CircuitBreaker("s", cb.CircuitBreakerConfig(
            failure_threshold=1, cooldown_seconds=60))
        with self.assertRaises(RuntimeError):
            b.call(lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(b.call(lambda: 0, on_open=lambda: "fallback"), "fallback")


class TestRuntimeContract(unittest.TestCase):
    def test_detects_missing_package(self):
        # check_contract detects missing packages via the module-level
        # ``import_module`` (importlib.import_module) that _packages_ok calls,
        # NOT builtins.__import__ -- so we patch the name it actually uses.
        real_import_module = rc.import_module

        def fake_import_module(name, *a, **k):
            if name.split(".")[0] == "numpy":
                raise ImportError("no numpy")
            return real_import_module(name, *a, **k)

        with mock.patch.object(rc, "import_module", side_effect=fake_import_module):
            violations = rc.check_contract(rc.RuntimeContract(required_packages=("numpy",)))
        self.assertTrue(any("numpy" in v for v in violations))

    def test_passes_when_satisfied(self):
        violations = rc.check_contract(rc.RuntimeContract(
            required_packages=(), required_executable=None,
            min_python=(3, 0)))
        self.assertEqual(violations, [])

    def test_wrong_executable_detected(self):
        violations = rc.check_contract(rc.RuntimeContract(
            required_executable="C:/does/not/exist/python.exe"))
        self.assertTrue(any("interpreter" in v for v in violations))


class TestSubmitGate(unittest.TestCase):
    def test_blocks_on_hard_check_fail(self):
        checks = [
            {"name": "LOW_SHARPE", "result": "PASS"},
            {"name": "CONCENTRATED_WEIGHT", "result": "FAIL"},
        ]
        res = sg.gate_submission(region="IND", universe="TOP500", is_checks=checks)
        self.assertFalse(res.submit_allowed)
        self.assertIn("CONCENTRATED_WEIGHT", res.failed_checks)

    def test_blocks_on_region_floor(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"}]
        metrics = {"concentrated_weight": 0.5}
        res = sg.gate_submission(region="IND", universe="TOP500",
                                 is_checks=checks, is_metrics=metrics)
        self.assertFalse(res.submit_allowed)
        self.assertTrue(any("CONCENTRATED_WEIGHT" in r for r in res.reasons))

    def test_allows_clean_usa(self):
        checks = [{"name": "LOW_SHARPE", "result": "PASS"},
                  {"name": "CLUSTER_TEST", "result": "PASS"}]
        res = sg.gate_submission(region="USA", universe="TOP3000", is_checks=checks)
        self.assertTrue(res.submit_allowed)

    def test_pending_checks_are_not_blockers(self):
        checks = [{"name": "SELF_CORRELATION", "result": "PENDING"},
                  {"name": "PROD_CORRELATION", "result": "PENDING"}]
        res = sg.gate_submission(region="USA", universe="TOP3000", is_checks=checks)
        self.assertTrue(res.submit_allowed)


class _FakeResp:
    def __init__(self, status_code, text="", json_data=None, headers=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.headers = headers or {}
    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class TestResilientHttp(unittest.TestCase):
    def _make(self, fake_session):
        s = rh.ResilientSession("u", "p", max_attempts=3, base_backoff=0.001, max_backoff=0.005)
        s._session = fake_session
        return s

    def test_403_body_preserved_not_retried(self):
        resp = _FakeResp(403, text='{"message":"CONCENTRATED_WEIGHT fail"}',
                         json_data={"message": "CONCENTRATED_WEIGHT fail"})
        fake = mock.MagicMock()
        fake.post.return_value = resp
        s = self._make(fake)
        r = s.post("/alphas/x/submit")
        self.assertFalse(r.ok)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.body, {"message": "CONCENTRATED_WEIGHT fail"})
        self.assertEqual(fake.post.call_count, 1)  # not retried

    def test_500_retried_then_returns(self):
        ok = _FakeResp(200, json_data={"ok": True})
        err = _FakeResp(503, text="try later")
        fake = mock.MagicMock()
        fake.get.side_effect = [err, err, ok]
        s = self._make(fake)
        r = s.get("/alphas/x")
        self.assertTrue(r.ok)
        self.assertEqual(fake.get.call_count, 3)

    def test_network_error_returns_explicit_result(self):
        fake = mock.MagicMock()
        fake.get.side_effect = rh.requests.exceptions.Timeout("boom")
        s = self._make(fake)
        r = s.get("/alphas/x")
        self.assertFalse(r.ok)
        self.assertIsNone(r.status_code)
        self.assertIn("network", r.error)

    def test_bool_convenience(self):
        self.assertTrue(rh.HttpResult(ok=True, status_code=200))
        self.assertFalse(rh.HttpResult(ok=False, status_code=403))


if __name__ == "__main__":
    unittest.main(verbosity=2)
