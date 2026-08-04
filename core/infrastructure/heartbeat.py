"""Worker liveness via heartbeats.

THE PROBLEM THIS SOLVES
-----------------------
The existing supervisor only watches child *exit codes*. A child that is
alive but deadlocked (e.g. blocked on a synchronous call, or stuck in an
exception-retry loop that never advances) looks perfectly healthy to
``process.poll()``. We observed exactly this: the tree was "up" but
produced nothing for 2.5 hours.

THE FIX
-------
Each supervised worker runs a :class:`HeartbeatEmitter` background thread
that atomically writes a heartbeat file every ``interval`` seconds with
its PID, a timestamp, and the current task. A
:class:`LivenessChecker` (run by the supervisor) reads these files; any
heartbeat older than ``stale_after`` is reported as a hung worker, which
the supervisor kills and restarts.

Because the emitter is a *separate thread*, a worker blocked in its main
thread (e.g. on a long BRAIN simulation or a stuck network call) still
keeps heart-beating — so we do NOT falsely kill a worker that is merely
busy. We only kill when the whole process has stopped updating its
heartbeat, which is the true signature of a hang/deadlock.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_INTERVAL = 15.0         # seconds between heartbeats
DEFAULT_STALE_AFTER = 180.0     # seconds; older than this => considered hung


@dataclass
class HeartbeatData:
    pid: int
    label: str
    timestamp: float
    task: str = ""

    def to_file(self, path: Path) -> None:
        # Atomic write: temp file in same dir, then replace. Avoids a
        # reader seeing a half-written JSON if the process is killed mid-write.
        payload = json.dumps(
            {
                "pid": self.pid,
                "label": self.label,
                "timestamp": self.timestamp,
                "task": self.task,
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.timestamp)),
            },
            ensure_ascii=False,
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        try:
            tmp.replace(path)
        except OSError:
            path.write_text(payload, encoding="utf-8")

    @staticmethod
    def from_file(path: Path) -> Optional["HeartbeatData"]:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return HeartbeatData(
                pid=int(data.get("pid", -1)),
                label=str(data.get("label", "?")),
                timestamp=float(data.get("timestamp", 0.0)),
                task=str(data.get("task", "")),
            )
        except Exception:
            return None


class HeartbeatEmitter:
    """Background thread that keeps a worker's heartbeat file fresh.

    Usage::
        hb = HeartbeatEmitter(Path("hb_project_runtime.json"), label="project_runtime")
        hb.start()                 # begins emitting every `interval` seconds
        hb.update_task("simulating XYZ")
        ...
        hb.stop()                  # joins the thread
    """

    def __init__(
        self,
        path: Path,
        *,
        label: str,
        interval: float = DEFAULT_INTERVAL,
        pid: Optional[int] = None,
    ) -> None:
        self._path = Path(path)
        self._label = label
        self._interval = interval
        self._pid = pid if pid is not None else os.getpid()
        self._task = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"hb-{label}", daemon=True)
        self._lock = threading.Lock()

    def start(self) -> "HeartbeatEmitter":
        self._stop.clear()
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 2)

    def update_task(self, task: str) -> None:
        with self._lock:
            self._task = task

    def _emit(self) -> None:
        with self._lock:
            task = self._task
        HeartbeatData(
            pid=self._pid, label=self._label, timestamp=time.time(), task=task
        ).to_file(self._path)

    def _run(self) -> None:
        # Emit immediately so a freshly started worker is visible at once.
        self._emit()
        while not self._stop.wait(self._interval):
            self._emit()


class LivenessChecker:
    """Reads heartbeat files and reports hung workers."""

    def __init__(self, stale_after: float = DEFAULT_STALE_AFTER) -> None:
        self.stale_after = stale_after

    def check(self, heartbeat_path: Path) -> tuple[bool, Optional[HeartbeatData], str]:
        """Return (is_alive, data, reason).

        ``is_alive`` is False when the heartbeat is missing or older than
        ``stale_after``. The ``reason`` string explains why.
        """
        data = HeartbeatData.from_file(heartbeat_path)
        if data is None:
            return False, None, "heartbeat file missing"
        age = time.time() - data.timestamp
        if age > self.stale_after:
            return False, data, f"heartbeat stale ({age:.0f}s > {self.stale_after:.0f}s)"
        return True, data, "ok"


def make_heartbeat_dir() -> Path:
    """A stable directory for heartbeat files, OS-appropriate."""
    base = os.getenv("LOCALAPPDATA", tempfile.gettempdir())
    d = Path(base) / "Quant worker-Monitor" / "heartbeats"
    d.mkdir(parents=True, exist_ok=True)
    return d
