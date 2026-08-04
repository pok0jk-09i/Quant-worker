from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


class SingleInstanceGuard:
    """Cross-platform single-instance lock with stale-lock replacement.

    The lock has two layers:
      1. A metadata file at lock_path that records the owning PID.
      2. A separate lock file at lock_path + ".osl" that is opened with
         O_EXCL on POSIX or msvcrt.locking() on Windows — this prevents the
         race where two processes read "no lock", then both write.

    Stale-lock replacement: if the OS lock is already held but the recorded
    owner PID is not in the supplied active_pids set, the old lock files are
    removed and acquisition is retried once. This handles crashes where the
    previous owner died without calling release().
    """

    _OSL_SUFFIX = ".osl"

    def __init__(self, lock_path: Path, *, pid: int | None = None) -> None:
        self.lock_path = lock_path
        self.pid = int(pid if pid is not None else os.getpid())
        self._os_lock_path = Path(str(lock_path) + self._OSL_SUFFIX)
        self._os_lock_handle: object | None = None

    def read_metadata(self) -> dict[str, int | str]:
        if not self.lock_path.exists():
            return {}
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _acquire_os_lock(self) -> bool:
        """Acquire the OS-level lock. Returns True on success, False if held."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Open for write, create if missing. On Windows, msvcrt.locking
            # with LK_NBLCK will fail (raise OSError) if another process
            # holds the lock. On POSIX, fcntl.flock with LOCK_NB | LOCK_EX
            # does the same.
            self._os_lock_handle = open(self._os_lock_path, "w+")
            if sys.platform == "win32":
                import msvcrt
                # Lock 1 byte at position 0 in non-blocking mode
                msvcrt.locking(self._os_lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._os_lock_handle.fileno(), fcntl.LOCK_NB | fcntl.LOCK_EX)
            return True
        except (OSError, ImportError):
            # Lock held by another process, or platform-specific lock unavailable.
            if self._os_lock_handle is not None:
                try:
                    self._os_lock_handle.close()
                except Exception:
                    pass
                self._os_lock_handle = None
            return False

    def _write_metadata(self) -> None:
        """Write metadata after OS lock has been acquired."""
        payload = json.dumps(
            {"pid": self.pid, "acquired_at": time.time()},
            ensure_ascii=False,
            indent=2,
        )
        with self.lock_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)

    def _cleanup_stale_lock_files(self) -> None:
        """Remove lock files left behind by a dead owner."""
        for path in (self.lock_path, self._os_lock_path):
            try:
                if path.exists():
                    path.unlink()
            except FileNotFoundError:
                pass
            except SystemExit:
                # Some sandbox environments intercept rapid deletions with a
                # bulk-delete guard. Treat this as a best-effort cleanup.
                pass
            except Exception:
                pass

    def acquire(self, *, active_pids: set[int] | None = None) -> None:
        active = active_pids if active_pids is not None else set()

        # Phase 1: metadata check. Fast path for live owner and stale cleanup.
        meta = self.read_metadata()
        owner_pid = int(meta.get("pid", 0) or 0)
        if owner_pid and owner_pid in active:
            raise RuntimeError(f"lock already held by live pid {owner_pid}")
        if owner_pid and owner_pid not in active:
            # Stale owner: remove leftover files before attempting OS lock.
            self._cleanup_stale_lock_files()

        # Phase 2: acquire OS-level lock.
        if self._acquire_os_lock():
            try:
                self._write_metadata()
                return
            except Exception:
                self.release()
                raise

        # Phase 3: OS lock failed. Re-read metadata to determine whether the
        # owner is still alive.
        meta = self.read_metadata()
        owner_pid = int(meta.get("pid", 0) or 0)
        if owner_pid and owner_pid in active:
            raise RuntimeError(f"lock already held by live pid {owner_pid}")

        # Owner is dead or metadata is missing: clean up and retry once.
        self._cleanup_stale_lock_files()
        if self._acquire_os_lock():
            try:
                self._write_metadata()
                return
            except Exception:
                self.release()
                raise

        raise RuntimeError(f"lock already held by pid {owner_pid}")

    def release(self) -> None:
        try:
            if self._os_lock_handle is not None:
                if sys.platform == "win32":
                    try:
                        import msvcrt
                        msvcrt.locking(self._os_lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                    except (ImportError, OSError):
                        pass
                self._os_lock_handle.close()
                self._os_lock_handle = None
        except Exception:
            pass
        # Remove metadata file only if we still own it
        try:
            if self.lock_path.exists():
                meta = self.read_metadata()
                if int(meta.get("pid", 0) or 0) == self.pid:
                    self.lock_path.unlink()
        except FileNotFoundError:
            pass
        except SystemExit:
            pass
        except Exception:
            pass
        # Best-effort cleanup of OS lock file
        try:
            if self._os_lock_path.exists():
                self._os_lock_path.unlink()
        except FileNotFoundError:
            pass
        except SystemExit:
            pass
        except Exception:
            pass


def list_active_python_pids() -> set[int]:
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'python.exe' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: set[int] = set()
    for line in (result.stdout or "").splitlines():
        value = line.strip()
        if value.isdigit():
            pids.add(int(value))
    return pids
