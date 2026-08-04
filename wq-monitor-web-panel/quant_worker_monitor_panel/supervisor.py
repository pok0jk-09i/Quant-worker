"""Supervision Tree — hardened, liveness-aware process manager.

DESIGN PRINCIPLES (vs. the previous version)
--------------------------------------------
1. **Fail-fast on wrong environment.** The single biggest cause of
   outages was launching the tree with the wrong Python interpreter
   (a managed build missing ``requests``/``numpy``). We now assert a
   runtime contract at startup and refuse to run otherwise.

2. **Liveness, not just liveness-of-exit-code.** ``process.poll()`` only
   detects a *dead* child. A child that is alive but deadlocked (hung on
   a synchronous call, stuck in an exception-retry loop) looks healthy.
   Each critical child emits a heartbeat file; if it goes stale we KILL
   and RESTART it. The supervisor itself also writes a heartbeat so an
   external watchdog can revive the whole tree if the supervisor dies.

3. **No more "circuit breaker kills the whole tree".** Previously, when a
   critical child hit its restart limit the supervisor set
   ``_running = False`` and exited — taking the panel and adapter down
   with it, with nothing to restart it. Now a permanently-failing child
   is *disabled* (skipped) but the tree keeps running and the supervisor
   keeps its own heartbeat so the external watchdog stays effective.

Contrast with the old launch_stack:
  - OLD: launch-and-forget, no restart, zombie subprocesses accumulate
  - PREV: supervised tree, auto-restart, BUT whole-tree death on breaker
  - NOW: supervised tree + liveness + env contract + tree survives child death
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ── Make the research-tree infrastructure importable ─────────────────
_RESEARCH_ROOT = Path(
    os.getenv("QUANT WORKER_RESEARCH_ROOT", r"E:\Quant worker-CLEAN\wq-alpha-research")
)
if str(_RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_ROOT))

from core.infrastructure.heartbeat import (  # noqa: E402
    HeartbeatData,
    LivenessChecker,
    make_heartbeat_dir,
)
from core.infrastructure.runtime_contract import (  # noqa: E402
    RuntimeContract,
    assert_runtime_contract,
)

# ── Restart policy ───────────────────────────────────────────────────
MAX_RESTARTS = 10               # max restarts within the sliding window
RESTART_WINDOW_SECONDS = 600    # sliding window for restart counting
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 120.0

# If a child's heartbeat is older than this, it is considered hung and
# will be killed + restarted. Must be longer than the longest legitimate
# single blocking operation (BRAIN sims can take several minutes, but the
# heartbeat thread runs independently so a busy worker still beats).
LIVENESS_STALE_AFTER = 300.0

# Supervisor writes its own heartbeat this often; the external watchdog
# uses it to detect a dead supervisor (the one case poll() can't see).
SUPERVISOR_HEARTBEAT_INTERVAL = 5.0


@dataclass
class SupervisedProcess:
    """A single supervised child process."""

    label: str
    script: Path
    cwd: Path
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    is_critical: bool = False
    max_restarts: int = MAX_RESTARTS
    # Optional heartbeat file emitted by the child; used for liveness.
    heartbeat_path: Path | None = None

    # Runtime state
    process: subprocess.Popen[str] | None = None
    restart_count: int = 0
    restart_times: list[float] = field(default_factory=list)
    last_backoff: float = BASE_BACKOFF_SECONDS
    disabled: bool = False          # permanently-failed -> skipped, tree survives


class ProcessManager:
    """Supervision tree for Quant worker processes."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        heartbeat_dir: Path | None = None,
    ) -> None:
        self._children: list[SupervisedProcess] = []
        self._running = False
        self._executable = executable or sys.executable
        self._heartbeat_dir = heartbeat_dir or make_heartbeat_dir()
        self._liveness = LivenessChecker(stale_after=LIVENESS_STALE_AFTER)
        self._supervisor_heartbeat = self._heartbeat_dir / "supervisor.json"
        self._last_supervisor_beat = 0.0

        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        if sys.platform == "win32":
            try:
                signal.signal(signal.SIGBREAK, self._handle_signal)  # type: ignore[attr-defined]
            except AttributeError:
                pass

    # -- public API ------------------------------------------------------
    def add(self, child: SupervisedProcess) -> None:
        self._children.append(child)

    def start_all(self) -> None:
        self._running = True
        for child in self._children:
            self._start_one(child)

    # -- spawning --------------------------------------------------------
    def _start_one(self, child: SupervisedProcess) -> bool:
        try:
            env = os.environ.copy()
            env.update(child.env or {})
            # Use the PINNED executable, never the inherited one. This is
            # what stops a wrong-interpreter launcher from poisoning every
            # child.
            cmd = [self._executable, str(child.script)] + (child.args or [])
            proc = subprocess.Popen(cmd, cwd=str(child.cwd), text=True, env=env)
            child.process = proc
            print(f"[supervisor] {child.label} started (PID {proc.pid})", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[supervisor] {child.label} failed to start: {exc}", flush=True)
            return False

    def _should_restart(self, child: SupervisedProcess) -> bool:
        now = time.time()
        child.restart_times = [
            t for t in child.restart_times if now - t < RESTART_WINDOW_SECONDS
        ]
        if len(child.restart_times) >= child.max_restarts:
            # DECISION: disable this child but KEEP THE TREE ALIVE. The
            # previous code set self._running = False here, which killed
            # the panel + adapter and left nothing to restart the tree.
            print(
                f"[supervisor] {child.label}: max restarts ({child.max_restarts}) "
                f"in {RESTART_WINDOW_SECONDS}s — DISABLING child (tree stays up). "
                f"ALERT: investigate why {child.label} keeps dying.",
                flush=True,
            )
            child.disabled = True
            return False
        backoff = min(child.last_backoff * 2, MAX_BACKOFF_SECONDS)
        child.last_backoff = backoff
        print(f"[supervisor] {child.label}: restarting in {backoff:.0f}s", flush=True)
        time.sleep(backoff)
        child.restart_times.append(now)
        child.restart_count += 1
        return True

    # -- liveness --------------------------------------------------------
    def _check_liveness(self, child: SupervisedProcess) -> None:
        """Kill + restart a child whose heartbeat has gone stale."""
        if child.heartbeat_path is None or child.process is None:
            return
        alive, data, reason = self._liveness.check(child.heartbeat_path)
        if alive:
            return
        print(
            f"[supervisor] {child.label}: LIVENESS FAIL ({reason}) — "
            f"killing hung process PID {child.process.pid}",
            flush=True,
        )
        try:
            child.process.kill()
            child.process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        child.process = None
        # Force an immediate restart (bypass backoff) since this is a hang,
        # not a crash-loop we want to throttle.
        child.restart_times.append(time.time())
        child.restart_count += 1
        self._start_one(child)

    # -- monitor loop ----------------------------------------------------
    def monitor(self) -> None:
        while self._running:
            # Supervisor heartbeat for the external watchdog.
            now = time.time()
            if now - self._last_supervisor_beat >= SUPERVISOR_HEARTBEAT_INTERVAL:
                HeartbeatData(
                    pid=os.getpid(), label="supervisor", timestamp=now
                ).to_file(self._supervisor_heartbeat)
                self._last_supervisor_beat = now

            time.sleep(3)

            for child in self._children:
                if child.disabled or child.process is None:
                    continue

                # (1) Liveness check BEFORE exit-code check — catches hangs.
                self._check_liveness(child)
                if child.process is None:
                    # _check_liveness already restarted it.
                    continue

                # (2) Exit-code check.
                returncode = child.process.poll()
                if returncode is None:
                    continue  # still running and (presumably) alive

                print(
                    f"[supervisor] {child.label} exited with code {returncode}",
                    flush=True,
                )
                if not self._should_restart(child):
                    # Child disabled (see _should_restart) OR non-critical
                    # and out of restarts. Tree stays up regardless.
                    if not child.is_critical:
                        child.process = None
                    # Critical + disabled: leave process=None, loop continues.
                    continue

                if not self._start_one(child):
                    if child.is_critical:
                        child.disabled = True

    # -- cleanup ---------------------------------------------------------
    def cleanup(self) -> None:
        print("[supervisor] Shutting down...", flush=True)
        for child in self._children:
            if child.process is None:
                continue
            if child.process.poll() is not None:
                continue
            try:
                child.process.terminate()
            except Exception:  # noqa: BLE001
                pass
        deadline = time.time() + 5
        for child in self._children:
            if child.process is None:
                continue
            try:
                child.process.wait(timeout=max(0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                try:
                    child.process.kill()
                except Exception:  # noqa: BLE001
                    pass
        # Clean lock + stale heartbeat files.
        lock_dir = Path(
            os.getenv("LOCALAPPDATA", str(Path.home()))
        ) / "Quant worker-Monitor"
        for lock_file in lock_dir.glob("*.lock"):
            try:
                lock_file.unlink()
            except Exception:  # noqa: BLE001
                pass
        print("[supervisor] All processes stopped.", flush=True)

    def _handle_signal(self, signum: int, frame: object) -> None:
        print(f"\n[supervisor] Received signal {signum}, shutting down...", flush=True)
        self._running = False
        self.cleanup()
        sys.exit(0)


def assert_environment(executable: str | None = None) -> None:
    """Fail fast if the running interpreter / deps are wrong.

    When ``executable`` is provided we also require the *current*
    interpreter to match it (realpath), so a wrong-python launcher is
    rejected before it can poison the tree.
    """
    contract = RuntimeContract(
        min_python=(3, 11),
        required_packages=("requests", "numpy"),
        required_executable=executable,
    )
    assert_runtime_contract(contract, exit_on_violation=True)
