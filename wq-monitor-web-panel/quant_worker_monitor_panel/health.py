"""Health Aggregation Engine — Microsoft Health Endpoint Pattern.

Layered health checks:
  Layer 1 — Liveness:  "Is the process alive?"  (heartbeat freshness)
  Layer 2 — Readiness: "Can it do useful work?" (state valid, no hard errors)
  Layer 3 — Aggregate:  "What's the system status?" (weighted summary)

Design principles (from Microsoft architecture-center):
  - Core services failure → DOWN (异常)
  - Auxiliary service failure → DEGRADED (降级) if core is healthy
  - Stale data is treated as DEGRADED, not DOWN
  - Health status is CACHED — not re-computed on every request
  - HTTP-style mapping: 200=OK, 503=DOWN, 429/partial=DEGRADED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# ── Staleness thresholds (seconds) ─────────────────────────────────────────
# Kubernetes-style: single miss does NOT flip health state.
# failureThreshold consecutive misses are required to trigger unhealthy.
# periodSeconds ≈ heartbeat interval; failureThreshold × periodSeconds
# should exceed the threshold to avoid false positives.
PROJECT_RUNTIME_HEARTBEAT_INTERVAL = 15   # heartbeat every ~15s
ADAPTER_HEARTBEAT_INTERVAL = 30          # adapter updates every ~30s
PANEL_HEARTBEAT_INTERVAL = 30            # panel refresh ~30s

# "How many consecutive stale checks before we call it dead?"
FAILURE_THRESHOLD_CORE = 5    # 5 consecutive misses for core (project_runtime)
FAILURE_THRESHOLD_AUX = 3     # 3 for auxiliary (adapter, panel)

# Effective staleness = failureThreshold × heartbeatInterval + buffer
PROJECT_RUNTIME_STALE_SECONDS = FAILURE_THRESHOLD_CORE * PROJECT_RUNTIME_HEARTBEAT_INTERVAL  # 75s
ADAPTER_STALE_SECONDS = FAILURE_THRESHOLD_AUX * ADAPTER_HEARTBEAT_INTERVAL  # 90s
PANEL_STALE_SECONDS = 120  # unchanged

# ── Health state tracker ──────────────────────────────────────────────────
# Tracks consecutive stale counts across aggregate() calls to implement
# K8s failureThreshold semantics. Reset to 0 on fresh heartbeat.
_HEALTH_TRACKER: dict[str, dict[str, int]] = {
    "project_runtime": {"stale_count": 0},
    "adapter_host": {"stale_count": 0},
    "panel_data": {"stale_count": 0},
}


def reset_health_tracker() -> None:
    """Reset the internal stale counters. Useful for tests and cold restarts."""
    for tracker in _HEALTH_TRACKER.values():
        tracker["stale_count"] = 0


@dataclass
class ComponentHealth:
    """Single component's health snapshot."""

    name: str
    is_core: bool = False
    liveness: bool = False
    readiness: bool = False
    detail: str = ""
    last_seen: datetime | None = None

    def is_stale(self, threshold_seconds: float) -> bool:
        if self.last_seen is None:
            return True
        return (datetime.now(timezone.utc) - self.last_seen) > timedelta(
            seconds=threshold_seconds
        )


@dataclass
class AggregatedHealth:
    """Final health verdict with all component details."""

    status: str  # "正常" | "降级" | "异常"
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    summary_lines: list[str] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return self.status == "正常"

    @property
    def is_down(self) -> bool:
        return self.status == "异常"


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        return None


def assess_project_runtime(project_state: dict[str, Any]) -> ComponentHealth:
    """Assess project_runtime: the AUTHORITY source.

    Liveness: heartbeat within PROJECT_RUNTIME_STALE_SECONDS, with K8s
    failureThreshold — requires 5 consecutive stale checks to trigger.
    Readiness: project_health=HEALTHY, no hard submit failure.
    """
    raw_health = str(project_state.get("project_health", "") or "").strip().upper()
    submit_status = str(project_state.get("submit_status", "") or "").strip().lower()
    submit_failure = project_state.get("submit_failure_kind", "")

    heartbeat = _parse_iso(project_state.get("heartbeat_at"))
    is_currently_stale = heartbeat is None or (
        (datetime.now(timezone.utc) - heartbeat)
        > timedelta(seconds=PROJECT_RUNTIME_HEARTBEAT_INTERVAL * 2)
    )

    tracker = _HEALTH_TRACKER["project_runtime"]
    if is_currently_stale:
        tracker["stale_count"] += 1
    else:
        tracker["stale_count"] = 0

    # K8s-style: only mark as dead after failureThreshold consecutive misses
    liveness = tracker["stale_count"] < FAILURE_THRESHOLD_CORE

    readiness = raw_health in {"HEALTHY", "正常"}
    detail = ""

    if not liveness:
        detail = f"project_runtime 心跳超时 ({tracker['stale_count']}/{FAILURE_THRESHOLD_CORE} 连续过时)"
    elif not readiness:
        detail = f"project_health={raw_health}"
    elif submit_status in {"error", "failed", "rejected", "platform_reject", "blocked"}:
        readiness = False
        detail = f"submit_status={submit_status}"
    elif submit_status == "degraded" and submit_failure not in {
        "mixed_non_active",
        "mixed_partial_success",
    }:
        readiness = False
        detail = f"submit degraded: {submit_failure}"

    return ComponentHealth(
        name="project_runtime",
        is_core=True,
        liveness=liveness,
        readiness=readiness,
        detail=detail,
        last_seen=heartbeat,
    )


def assess_adapter(adapter_state: dict[str, Any]) -> ComponentHealth:
    """Assess adapter_host: the DERIVED source.

    Liveness: adapter_state updated within ADAPTER_STALE_SECONDS, with K8s
    failureThreshold — requires 3 consecutive stale checks.
    Readiness: adapter_status=RUNNING, no unexpected failure
    """
    status = str(adapter_state.get("adapter_status", "") or "").strip().upper()
    failure = str(adapter_state.get("failure_kind", "") or "").strip().lower()
    updated = _parse_iso(adapter_state.get("updated_at"))

    is_currently_stale = updated is None or (
        (datetime.now(timezone.utc) - updated)
        > timedelta(seconds=ADAPTER_HEARTBEAT_INTERVAL * 2)
    )

    tracker = _HEALTH_TRACKER["adapter_host"]
    if is_currently_stale:
        tracker["stale_count"] += 1
    else:
        tracker["stale_count"] = 0

    liveness = tracker["stale_count"] < FAILURE_THRESHOLD_AUX

    readiness = status in {"RUNNING", "HEALTHY", "正常"}
    detail = ""

    if not liveness:
        detail = f"adapter_state 超过阈值未更新 ({tracker['stale_count']}/{FAILURE_THRESHOLD_AUX})"
    elif not readiness:
        detail = f"adapter_status={status}, failure={failure}"
    elif failure and failure != "none":
        readiness = False
        detail = f"adapter failure: {failure}"

    return ComponentHealth(
        name="adapter_host",
        is_core=False,
        liveness=liveness,
        readiness=readiness,
        detail=detail,
        last_seen=updated,
    )


def assess_panel(error_text: str) -> ComponentHealth:
    """Assess panel's own hit-fetch capability."""
    text = str(error_text or "").strip()
    if not text:
        return ComponentHealth(
            name="panel_data",
            is_core=False,
            liveness=True,
            readiness=True,
            detail="hit fetch OK",
        )

    is_offline = (
        "缺少 BRAIN 凭据" in text
        or "认证失败" in text
        or ("Connection aborted" in text and "10053" not in text)
    )

    return ComponentHealth(
        name="panel_data",
        is_core=False,
        liveness=True,
        readiness=not is_offline,
        detail=text[:120],
    )


def aggregate(
    project_state: dict[str, Any] | None,
    adapter_state: dict[str, Any] | None,
    error_text: str = "",
) -> AggregatedHealth:
    """Produce the unified health verdict.

    Rules (inspired by Microsoft Health Endpoint Pattern):
      - If ANY core component is NOT live → 异常
      - If ANY core component is live but NOT ready → 异常
      - If ALL core components are ready but auxiliary is NOT ready → 降级
      - If no component data is available → 异常 (system dark)
      - If only auxiliary data is stale → 降级
    """
    project = project_state if isinstance(project_state, dict) else {}
    adapter = adapter_state if isinstance(adapter_state, dict) else {}

    pr = assess_project_runtime(project)
    ad = assess_adapter(adapter)
    pn = assess_panel(error_text)

    components = {
        "project_runtime": pr,
        "adapter_host": ad,
        "panel_data": pn,
    }

    # Core components must be live and ready
    core_failures: list[str] = []
    for comp in components.values():
        if not comp.is_core:
            continue
        if not comp.liveness:
            core_failures.append(f"{comp.name}: 不存活 ({comp.detail})")
        elif not comp.readiness:
            core_failures.append(f"{comp.name}: 未就绪 ({comp.detail})")

    if core_failures:
        return AggregatedHealth(
            status="异常",
            components=components,
            summary_lines=[f"核心组件异常: {', '.join(core_failures)}"],
        )

    # If no component has any data at all → system dark
    if not pr.liveness and not ad.liveness:
        # But we already passed core_failures above (which would catch pr
        # being down). This branch catches the edge case where BOTH
        # project AND adapter are silent but somehow core check passed.
        # (Shouldn't happen in practice, but defensive.)
        return AggregatedHealth(status="异常", components=components,
                                summary_lines=["系统无数据: 所有组件均不可达"])

    # All cores ready → now check auxiliary
    auxiliary_issues: list[str] = []

    if not ad.liveness:
        auxiliary_issues.append("adapter_host 数据过时")
    elif not ad.readiness:
        auxiliary_issues.append(f"adapter_host: {ad.detail}")

    if not pn.readiness:
        auxiliary_issues.append(f"panel_data: {pn.detail}")

    if auxiliary_issues:
        return AggregatedHealth(
            status="降级",
            components=components,
            summary_lines=auxiliary_issues,
        )

    return AggregatedHealth(status="正常", components=components, summary_lines=[])
