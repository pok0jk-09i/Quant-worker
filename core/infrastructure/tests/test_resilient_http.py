"""Regression tests for ResilientSession authentication wiring.

Run: python -m pytest core/infrastructure/tests/test_resilient_http.py

These tests pin the bug fixed on 2026-08-01:
  authenticate() called self.post(..., _is_auth=True) but post()/request()
  never forwarded _is_auth to _do(), so every auth attempt raised
  "TypeError: ResilientSession.post() got an unexpected keyword argument
  '_is_auth'" — which crashed candidate_submitter.create_session() and drove
  the monitor panel health to ERROR.

All tests are OFFLINE: the network Session is mocked.
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from core.infrastructure import resilient_http as rh  # noqa: E402


class _FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers: dict = {}

    def json(self):
        if self._json is None:
            raise ValueError("no json in response")
        return self._json


class TestResilientAuth(unittest.TestCase):
    def _make(self) -> "rh.ResilientSession":
        return rh.ResilientSession("u", "p")

    # ── RED anchor: the exact crash from the live failure ────────────
    def test_authenticate_no_typeerror_and_returns_201(self):
        s = self._make()
        fake = _FakeResponse(201, {"status": "OK"})
        with mock.patch.object(s._session, "post", return_value=fake) as m:
            res = s.authenticate()  # must NOT raise TypeError
        self.assertIsInstance(res, rh.HttpResult)
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.ok)
        args, kwargs = m.call_args
        self.assertTrue(str(args[0]).endswith("/authentication"))
        self.assertIsNone(kwargs.get("json"))

    def test_authenticate_terminal_on_401_no_reauth_loop(self):
        # authenticate() passes _is_auth=True, so a 401 must be returned as a
        # terminal result (NOT trigger an internal re-auth recursion).
        s = self._make()
        fake = _FakeResponse(401, {"error": "bad creds"})
        with mock.patch.object(s._session, "post", return_value=fake):
            res = s.authenticate()
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.ok)

    def test_get_401_triggers_single_reauth(self):
        # A normal request that gets 401 must re-authenticate once, then
        # succeed on retry. This guards the _is_auth recursion guard too.
        s = self._make()
        get_seq = [_FakeResponse(401), _FakeResponse(200, {"ok": 1})]
        auth_seq = [_FakeResponse(201, {"status": "OK"})]
        calls: list[tuple[str, str]] = []

        def fake_post(url, json=None, timeout=None):
            calls.append(("POST", str(url)))
            return auth_seq.pop(0)

        def fake_get(url, timeout=None):
            calls.append(("GET", str(url)))
            return get_seq.pop(0)

        with mock.patch.object(s._session, "post", side_effect=fake_post), \
             mock.patch.object(s._session, "get", side_effect=fake_get):
            res = s.get("/x")

        self.assertEqual(res.status_code, 200)
        auth_calls = [c for c in calls if c[0] == "POST"
                      and c[1].endswith("/authentication")]
        self.assertEqual(
            auth_calls,
            [("POST", "https://api.worldquantbrain.com/authentication")],
            "exactly one re-auth POST /authentication expected",
        )

    def test_body_preserved_on_403_for_diagnostics(self):
        # Contract: permanent 4xx bodies must be preserved so callers can
        # read BRAIN rejection reasons (e.g. CONCENTRATED_WEIGHT).
        s = self._make()
        fake = _FakeResponse(403, {"is": {"checks": [{"name": "CONCENTRATED_WEIGHT",
                                                       "result": "FAIL"}]}})
        with mock.patch.object(s._session, "post", return_value=fake):
            res = s.post("/alphas/abc/submit")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(res.ok)
        self.assertIsNotNone(res.body)
        self.assertEqual(res.body["is"]["checks"][0]["name"], "CONCENTRATED_WEIGHT")


if __name__ == "__main__":
    unittest.main()
