import tempfile
import unittest
from pathlib import Path

from quant_worker_monitor_panel.single_instance import SingleInstanceGuard


class SingleInstanceGuardTests(unittest.TestCase):
    def test_acquire_uses_exclusive_create_to_block_racing_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "quant_worker_panel.lock"
            first = SingleInstanceGuard(lock_path, pid=1001)
            second = SingleInstanceGuard(lock_path, pid=1002)

            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire(active_pids={1001})
            finally:
                first.release()

    def test_acquire_creates_lock_file_and_rejects_second_live_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "quant_worker_panel.lock"
            first = SingleInstanceGuard(lock_path, pid=1001)
            second = SingleInstanceGuard(lock_path, pid=1002)

            first.acquire()
            try:
                self.assertTrue(lock_path.exists())
                with self.assertRaises(RuntimeError):
                    second.acquire(active_pids={1001})
            finally:
                first.release()

    def test_acquire_replaces_stale_lock_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "quant_worker_panel.lock"
            first = SingleInstanceGuard(lock_path, pid=1001)
            second = SingleInstanceGuard(lock_path, pid=1002)

            first.acquire()
            first.release()
            second.acquire()
            try:
                self.assertEqual(second.read_metadata()["pid"], 1002)
            finally:
                second.release()


if __name__ == "__main__":
    unittest.main()
