"""Infrastructure primitives for resilient long-running operation.

Public surface:
  - runtime_contract : fail-fast guard against wrong interpreter / missing deps
  - circuit_breaker  : standard OPEN/HALF_OPEN/CLOSED breaker
  - resilient_http   : retry + jitter + breaker + body-preserving HTTP client
  - heartbeat        : worker liveness emitter + supervisor liveness checker
  - submit_gate      : region-aware pre-submission quality gate
  - thresholds       : verified sub-universe Sharpe absolute-floor formula (P0)
  - oos_evaluator    : cross-validated OOS overfitting gate (P0)
  - brain_reconcile  : reconcile local DB with BRAIN platform truth
"""
