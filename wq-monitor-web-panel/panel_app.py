from __future__ import annotations

import json
import os
import socket
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from quant_worker_monitor_panel.core import (
    build_adapter_summary_lines,
    build_offline_summary_lines,
    now_beijing,
    describe_project_progress,
    build_project_summary_lines,
    build_summary_lines,
    format_alpha_card,
    select_qualifying_alphas,
)
from quant_worker_monitor_panel.guardian import browser_health_label, should_reopen_browser
from quant_worker_monitor_panel.health import aggregate as compute_overall_health
from quant_worker_monitor_panel.resilience import alpha_fetch_breaker, auth_breaker
from quant_worker_monitor_panel.notifier import (
    build_error_popup,
    build_factor_popup,
    build_offline_popup,
    should_popup_for_error,
)
from quant_worker_monitor_panel.single_instance import SingleInstanceGuard, list_active_python_pids

ROOT = Path(__file__).resolve().parent
API_BASE = "https://api.worldquantbrain.com"
DEFAULT_PORT = 8765
STATE_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Quant worker-Monitor"
LOG_PATH = STATE_DIR / "panel.log"
PANEL_STATE_PATH = STATE_DIR / "panel_state.json"
PROJECT_RUNTIME_STATE_PATH = STATE_DIR / "project_runtime_state.json"
ADAPTER_STATE_PATH = STATE_DIR / "adapter_state.json"
PANEL_LOCK_PATH = STATE_DIR / "panel_app.lock"
REFRESH_SECONDS = int(os.getenv("QUANT WORKER_PANEL_REFRESH_SECONDS", "30"))
FITNESS_THRESHOLD = 1.5
SHARPE_THRESHOLD = 1.5
MAX_ITEMS = 100
HEARTBEAT_MAX_AGE_SECONDS = 120  # Don't reopen immediately — browser may be fine
REOPEN_COOLDOWN_SECONDS = 300    # 5 min cooldown to prevent infinite reopen loops
MAX_REOPEN_COUNT = 2             # Absolute cap on browser reopens per session

EVENTS: list[str] = []
LATEST: dict[str, Any] = {
    "health": "初始化中",
    "raw_hits": [],
    "hits": [],
    "summary": [],
    "adapter_summary": [],
    "project_summary": [],
    "project_state": {},
    "adapter_state": {},
    "project_progress": "",
    "panel_port": DEFAULT_PORT,
    "panel_url": f"http://127.0.0.1:{DEFAULT_PORT}",
}
LAST_PING: datetime | None = None
LAST_OPEN: datetime | None = None
PAGE_HEARTBEAT: datetime | None = None
SEEN_HIT_IDS: set[str] = set()
HIT_BASELINE_INITIALIZED = False
LAST_ERROR_TEXT: str | None = None
ACTIVE_PORT: int = DEFAULT_PORT


def ensure_single_instance() -> SingleInstanceGuard:
    guard = SingleInstanceGuard(PANEL_LOCK_PATH)
    guard.acquire(active_pids=list_active_python_pids())
    return guard


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def log(msg: str) -> None:
    stamp = now_beijing().strftime("%Y-%m-%d %H:%M:%S 北京时间")
    line = f"[{stamp}] {msg}"
    EVENTS.append(line)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _rotate_panel_log_if_needed(LOG_PATH)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


# Log rotation: keep last 3 files, max 2MB each. panel.log grows
# ~3KB per refresh cycle (every REFRESH_SECONDS, default 30s), so
# 2MB ≈ 18 hours of continuous operation.
PANEL_LOG_MAX_BYTES = 2 * 1024 * 1024
PANEL_LOG_KEEP = 3


def _rotate_panel_log_if_needed(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < PANEL_LOG_MAX_BYTES:
            return
    except OSError:
        return
    oldest = path.with_suffix(path.suffix + f".{PANEL_LOG_KEEP}")
    try:
        if oldest.exists():
            oldest.unlink()
    except OSError:
        pass
    for i in range(PANEL_LOG_KEEP - 1, 0, -1):
        src = path.with_suffix(path.suffix + f".{i}")
        dst = path.with_suffix(path.suffix + f".{i + 1}")
        if src.exists():
            try:
                src.rename(dst)
            except OSError:
                pass
    try:
        path.rename(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def notify(title: str, body: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, body, title, 0x40)
    except Exception as exc:
        log(f"弹窗失败: {exc}")


def panel_url(port: int | None = None) -> str:
    target_port = ACTIVE_PORT if port is None else port
    return f"http://127.0.0.1:{target_port}"


def compute_browser_health(
    *,
    last_ping: datetime | None,
    last_open: datetime | None,
    now: datetime | None = None,
) -> str:
    needs_reopen = should_reopen_browser(
        last_ping=last_ping,
        last_open=last_open,
        now=now or now_utc(),
        stale_after_seconds=HEARTBEAT_MAX_AGE_SECONDS,
        reopen_cooldown_seconds=REOPEN_COOLDOWN_SECONDS,
    )
    return browser_health_label(not needs_reopen)


def can_bind_port(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def choose_port(preferred_port: int, search_window: int = 30) -> int:
    if can_bind_port(preferred_port):
        return preferred_port

    for port in range(preferred_port + 1, preferred_port + search_window + 1):
        if can_bind_port(port):
            return port

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def load_credentials() -> tuple[str, str]:
    user = os.getenv("WQ_BRAIN_USERNAME")
    password = os.getenv("WQ_BRAIN_PASSWORD")
    if user and password:
        return user, password
    cred = ROOT / "credential.txt"
    if cred.exists():
        user, password = json.loads(cred.read_text(encoding="utf-8"))
        return str(user), str(password)
    raise FileNotFoundError("缺少 BRAIN 凭据，请先配置 WQ_BRAIN_USERNAME / WQ_BRAIN_PASSWORD")


def create_session() -> requests.Session:
    if not auth_breaker.allow_request():
        raise RuntimeError("认证断路器已熔断，暂停 API 调用")
    user, password = load_credentials()
    session = requests.Session()
    session.auth = HTTPBasicAuth(user, password)
    session.headers.update({"Accept": "application/json;version=2.0", "Content-Type": "application/json"})
    try:
        response = session.post(f"{API_BASE}/authentication", timeout=30)
        if response.status_code != 201:
            auth_breaker.record_failure()
            raise RuntimeError(f"认证失败: {response.status_code} {response.text}")
        auth_breaker.record_success()
        return session
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        auth_breaker.record_failure()
        raise


def reauth_if_needed(session: requests.Session) -> bool:
    """Re-authenticate when the session has been kicked out by the server.

    Returns True if a fresh session was obtained, False if the current one
    is still valid.
    """
    try:
        resp = session.get(f"{API_BASE}/users/self", timeout=10)
        if resp.status_code == 200:
            return False
        if resp.status_code not in (401, 403):
            return False
    except Exception:
        # Connection-level error — try re-authenticating rather than
        # declaring the session invalid from a transient timeout.
        pass
    try:
        resp = session.post(f"{API_BASE}/authentication", timeout=30)
        return resp.status_code == 201
    except Exception:
        return False


def _get_with_resilience(session: requests.Session, url: str, **kwargs) -> requests.Response | None:
    """HTTP GET that survives 429, 401, and connection aborts.

    - 429: exponential backoff up to 5 retries
    - 401: re-authenticate and retry once
    - ConnectionError/ConnectionAbortedError: re-authenticate (token likely
      invalidated by the server) and retry

    Wrapped with alpha_fetch_breaker for circuit-breaker protection.
    """
    if not alpha_fetch_breaker.allow_request():
        raise RuntimeError("alpha fetch 断路器已熔断，暂停 API 调用")

    for attempt in range(6):
        try:
            resp = session.get(url, timeout=kwargs.pop("timeout", 60), **kwargs)
            if resp.status_code == 429:
                retry_after_raw = resp.headers.get("Retry-After", "5")
                try:
                    wait = min(int(retry_after_raw), 60)
                except (ValueError, TypeError):
                    wait = 5
                wait = min(wait * (2 ** attempt), 120)
                time.sleep(wait)
                continue
            if resp.status_code in (401, 403):
                if reauth_if_needed(session):
                    continue
            alpha_fetch_breaker.record_success()
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                ConnectionAbortedError):
            # Token likely invalidated. Re-auth and retry.
            if reauth_if_needed(session):
                continue
            alpha_fetch_breaker.record_failure()
            return None
    alpha_fetch_breaker.record_failure()
    return None


def fetch_top_hits(session: requests.Session) -> list[dict[str, Any]]:
    resp = _get_with_resilience(session, f"{API_BASE}/users/self/alphas",
                                params={"limit": MAX_ITEMS, "offset": 0})
    if resp is None:
        raise RuntimeError("all retries exhausted for fetch_top_hits")
    if resp.status_code == 429:
        raise RuntimeError("API rate limit exceeded")
    resp.raise_for_status()
    data = resp.json()
    alphas = data.get("results", [])
    return select_qualifying_alphas(alphas, threshold=FITNESS_THRESHOLD, sharpe_threshold=SHARPE_THRESHOLD, max_items=MAX_ITEMS)


def read_project_runtime_state() -> dict[str, Any]:
    if not PROJECT_RUNTIME_STATE_PATH.exists():
        return {
            "status": "NOT_STARTED",
            "project_health": "未启动",
            "mode": "unknown",
            "cycle_count": 0,
            "last_leaf_job": "",
            "last_error": "",
        }
    try:
        data = json.loads(PROJECT_RUNTIME_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "STATE_ERROR",
            "project_health": "异常",
            "mode": "unknown",
            "cycle_count": 0,
            "last_leaf_job": "",
            "last_error": str(exc),
        }
    return data if isinstance(data, dict) else {}


def read_adapter_state() -> dict[str, Any]:
    if not ADAPTER_STATE_PATH.exists():
        return {
            "adapter_status": "NOT_STARTED",
            "failure_kind": "none",
            "last_error": "",
            "last_leaf_job": "",
        }
    try:
        data = json.loads(ADAPTER_STATE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "adapter_status": "STATE_ERROR",
            "failure_kind": "unexpected",
            "last_error": str(exc),
            "last_leaf_job": "",
        }
    return data if isinstance(data, dict) else {}


def persist_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PANEL_STATE_PATH.write_text(json.dumps(LATEST, ensure_ascii=False, indent=2), encoding="utf-8")


def update_live_state(
    *,
    hits: list[dict[str, Any]],
    summary: list[str],
    error_text: str,
) -> None:
    project_state = read_project_runtime_state()
    adapter_state = read_adapter_state()
    health_pack = compute_overall_health(
        project_state=project_state,
        adapter_state=adapter_state,
        error_text=error_text,
    )
    LATEST.update(
        {
            "health": health_pack.status,
            "raw_hits": hits,
            "hits": [format_alpha_card(alpha) for alpha in hits],
            "summary": summary,
            "project_summary": build_project_summary_lines(project_state),
            "project_progress": describe_project_progress(str(project_state.get("last_progress", "") or "")),
            "progress_at": str(project_state.get("heartbeat_at") or project_state.get("updated_at") or ""),
            "adapter_summary": build_adapter_summary_lines(adapter_state),
            "authority_map": adapter_state.get("authority_map", {}),
            "workflow_verdicts": adapter_state.get("workflow_verdicts", {}),
            "business_impact": adapter_state.get("business_impact", []),
            "next_attention": adapter_state.get("next_attention", ""),
            "project_state": project_state,
            "adapter_state": adapter_state,
            "error": error_text,
            "updated_at": LAST_PING.isoformat() if LAST_PING else "",
            "heartbeat_at": LAST_PING.isoformat() if LAST_PING else "",
            "panel_port": ACTIVE_PORT,
            "panel_url": panel_url(),
            "health_components": {
                name: {
                    "liveness": c.liveness,
                    "readiness": c.readiness,
                    "detail": c.detail,
                    "is_core": c.is_core,
                }
                for name, c in health_pack.components.items()
            },
            "health_summary": health_pack.summary_lines,
        }
    )


def update_loop() -> None:
    global LAST_PING, LAST_ERROR_TEXT, SEEN_HIT_IDS, HIT_BASELINE_INITIALIZED
    while True:
        try:
            session = create_session()
            hits = fetch_top_hits(session)
            LAST_PING = now_utc()
            summary_lines = build_summary_lines(hits, threshold=FITNESS_THRESHOLD)
            update_live_state(hits=hits, summary=summary_lines, error_text="")
            log(f"监控正常，命中 {len(hits)} 个 Fitness>={FITNESS_THRESHOLD} & Sharpe>={SHARPE_THRESHOLD} 的因子")
            LAST_ERROR_TEXT = None

            new_ids = {str(item.get('id', '')).strip() for item in hits if str(item.get('id', '')).strip()}
            if not HIT_BASELINE_INITIALIZED:
                SEEN_HIT_IDS.update(new_ids)
                HIT_BASELINE_INITIALIZED = True
            else:
                unseen = new_ids - SEEN_HIT_IDS
                if unseen:
                    title, body = build_factor_popup(hits, threshold=FITNESS_THRESHOLD, max_preview=3)
                    notify(title, body)
                    SEEN_HIT_IDS.update(unseen)
        except Exception as exc:
            LAST_PING = now_utc()
            error_text = str(exc)
            if "缺少 BRAIN 凭据" in error_text:
                title, body = build_offline_popup()
                update_live_state(hits=[], summary=build_offline_summary_lines(), error_text="")
                log("离线运行：缺少凭据，但面板继续可观测")
                if should_popup_for_error(title + body, LAST_ERROR_TEXT):
                    notify(title, body)
                    LAST_ERROR_TEXT = title + body
            else:
                update_live_state(hits=[], summary=LATEST.get("summary", []), error_text=error_text)
                log(f"监控异常: {exc}")
                if should_popup_for_error(error_text, LAST_ERROR_TEXT):
                    title, body = build_error_popup(error_text)
                    notify(title, body)
                    LAST_ERROR_TEXT = error_text

        persist_state()
        time.sleep(REFRESH_SECONDS)


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
  <meta http-equiv="Pragma" content="no-cache" />
  <meta http-equiv="Expires" content="0" />
  <title>Quant worker 监控面板</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif; margin:0; background:#0b1020; color:#e8eefc; }
    .wrap { display:grid; grid-template-columns: 1.1fr 1.2fr; gap:16px; padding:16px; min-height:100vh; box-sizing:border-box; }
    .card { background:#121933; border:1px solid #243059; border-radius:16px; padding:16px; overflow:auto; }
    h1,h2 { margin:0 0 12px 0; }
    pre { white-space:pre-wrap; word-break:break-word; background:#0a0f1f; padding:12px; border-radius:12px; border:1px solid #23304e; }
    .ok { color:#86efac; }
    .bad { color:#fda4af; }
    .warn { color:#fbbf24; }
    .muted { color:#94a3b8; font-size:12px; }
    .progress-box { display:flex; align-items:center; gap:10px; margin:8px 0; }
    .progress-pulse { width:10px; height:10px; border-radius:50%; background:#86efac; animation:pulse 1.5s infinite; }
    @keyframes pulse { 0% { opacity:1; transform:scale(1); } 50% { opacity:.4; transform:scale(.85); } 100% { opacity:1; transform:scale(1); } }
    .progress-stale { background:#fbbf24; animation:none; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Quant worker 监控面板</h1>
      <div id="health" class="muted">加载中...</div>
      <div class="muted" id="updated"></div>
      <div class="muted" id="heartbeat"></div>
      <div class="muted" id="page-heartbeat"></div>
      <div class="muted" id="panel-url"></div>
      <div class="muted" id="version-info">v2026-07-09-13 (K8s-FailureThreshold)</div>
      <div id="project-progress" class="progress-box"></div>
      <h2>项目运行态</h2>
      <pre id="project-summary"></pre>
      <h2>适配器状态</h2>
      <pre id="adapter-summary"></pre>
      <h2>因子监控总览</h2>
      <pre id="summary"></pre>
      <h2>运行日志</h2>
      <pre id="events"></pre>
    </div>
    <div class="card">
      <h2>命中因子</h2>
      <pre id="hits"></pre>
      <h2>异常信息</h2>
      <pre id="error"></pre>
    </div>
  </div>
  <script>
    async function pingPage() {
      await fetch('/page-ping', { method: 'POST' });
    }
    async function refresh() {
      const res = await fetch('/state');
      const data = await res.json();
      const healthy = data.overall_health === '正常';
      const degraded = data.overall_health === '降级';
      const cssClass = healthy ? 'ok' : (degraded ? 'warn' : 'bad');
      document.getElementById('health').innerHTML = '健康状态: <span class="' + cssClass + '">' + data.overall_health + '</span>';
      document.getElementById('updated').textContent = '更新时间: ' + (data.updated_at || '');
      document.getElementById('heartbeat').textContent = '数据心跳: ' + (data.heartbeat_at || '');
      document.getElementById('page-heartbeat').textContent = '页面心跳: ' + (data.page_heartbeat_at || '');
      document.getElementById('panel-url').textContent = '面板地址: ' + (data.panel_url || '');
      const progressText = data.project_progress || '暂无';
      const isRunning = /progress|polling|simulating|starting|fetching|running/i.test(progressText);
      const progressHtml = '<div class="progress-pulse ' + (isRunning ? '' : 'progress-stale') + '"></div>' +
        '<span class="ok">' + (isRunning ? '进行中: ' : '当前进度: ') + progressText + '</span>' +
        '<span class="muted">(更新: ' + (data.progress_at || 'unknown') + ')</span>';
      document.getElementById('project-progress').innerHTML = progressHtml;
      document.getElementById('project-summary').textContent = (data.project_summary || []).join('\\n');
      document.getElementById('adapter-summary').textContent = (data.adapter_summary || []).join('\\n');
      document.getElementById('summary').textContent = (data.summary || []).join('\\n');
      document.getElementById('events').textContent = (data.events || []).join('\\n');
      document.getElementById('hits').textContent = (data.hits || []).join('\\n\\n');
      document.getElementById('error').textContent = data.error || '';
      await pingPage();
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    # Force connection close to prevent thread leaks on ThreadingHTTPServer.
    # Without this, HTTP/1.1 keep-alive keeps threads alive indefinitely.
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
            return
        if self.path == "/state":
            # Refresh dynamic fields from disk, but NEVER re-inject a
            # stale error_text from LATEST — that overwrites the real
            # health with whatever transient error the hit-fetch last
            # produced. The real health should come from the background
            # update_loop, which persists LATEST every REFRESH_SECONDS.
            update_live_state(hits=LATEST.get("raw_hits", []), summary=LATEST.get("summary", []), error_text="")
            payload = dict(LATEST)
            payload["events"] = EVENTS[-200:]
            payload["page_heartbeat_at"] = PAGE_HEARTBEAT.isoformat() if PAGE_HEARTBEAT else ""
            payload["browser_health"] = compute_browser_health(
                last_ping=PAGE_HEARTBEAT,
                last_open=LAST_OPEN,
                now=now_utc(),
            )
            payload["overall_health"] = payload.get("health", "异常")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        global PAGE_HEARTBEAT
        if self.path == "/page-ping":
            PAGE_HEARTBEAT = now_utc()
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return


def browser_watchdog() -> None:
    global LAST_OPEN
    reopen_count = 0
    while True:
        time.sleep(5)
        if reopen_count >= MAX_REOPEN_COUNT:
            # Once the cap is hit, stop reopening entirely.
            # The user can still open the panel manually.
            continue
        if should_reopen_browser(
            last_ping=PAGE_HEARTBEAT,
            last_open=LAST_OPEN,
            now=now_utc(),
            stale_after_seconds=HEARTBEAT_MAX_AGE_SECONDS,
            reopen_cooldown_seconds=REOPEN_COOLDOWN_SECONDS,
        ):
            webbrowser.open(panel_url())
            LAST_OPEN = now_utc()
            reopen_count += 1
            log(f"浏览器窗口已恢复 (第{reopen_count}/{MAX_REOPEN_COUNT}次)")


def main() -> None:
    global ACTIVE_PORT, LAST_OPEN

    guard = ensure_single_instance()
    ACTIVE_PORT = choose_port(DEFAULT_PORT)
    if ACTIVE_PORT != DEFAULT_PORT:
        log(f"默认端口 {DEFAULT_PORT} 被占用，已切换到 {ACTIVE_PORT}")

    LATEST["panel_port"] = ACTIVE_PORT
    LATEST["panel_url"] = panel_url()
    persist_state()

    log("启动本地 Web 监控面板")
    try:
        threading.Thread(target=update_loop, daemon=True).start()
        threading.Thread(target=browser_watchdog, daemon=True).start()
        server = ThreadingHTTPServer(("127.0.0.1", ACTIVE_PORT), Handler)
        webbrowser.open(panel_url())
        LAST_OPEN = now_utc()
        server.serve_forever()
    finally:
        guard.release()


if __name__ == "__main__":
    main()
