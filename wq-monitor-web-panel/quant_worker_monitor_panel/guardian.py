from __future__ import annotations

from datetime import datetime, timezone


def browser_health_label(is_healthy: bool) -> str:
    return "正常" if is_healthy else "异常"


def should_reopen_browser(
    *,
    last_ping: datetime | None,
    last_open: datetime | None,
    now: datetime | None = None,
    stale_after_seconds: int = 60,
    reopen_cooldown_seconds: int = 30,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if last_ping is None:
        return False
    if last_ping.tzinfo is None:
        last_ping = last_ping.replace(tzinfo=timezone.utc)
    if last_open is not None and last_open.tzinfo is None:
        last_open = last_open.replace(tzinfo=timezone.utc)

    if (current - last_ping).total_seconds() < stale_after_seconds:
        return False
    if last_open is None:
        return True
    return (current - last_open).total_seconds() >= reopen_cooldown_seconds
