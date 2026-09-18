"""
Tests for ZARA Phase 15: Resource Locking Subsystem.
Verifies thread-safe fine-grained locking across filesystem paths, terminal,
GUI input devices (keyboard/mouse/screen), cyber targets, lock conflict detection,
re-entrancy, orphan cleanup, and timeouts.
"""
import time
import unittest
from pathlib import Path

from modules.resource_locking import (
    ResourceManager,
    ResourceLock,
    ResourceType,
    AccessMode
)


class TestResourceLocking(unittest.TestCase):
    def setUp(self):
        self.rm = ResourceManager(default_timeout=5.0)

    def tearDown(self):
        self.rm.clear()

    def test_01_exclusive_lock_acquisition(self):
        """Verify worker acquires exclusive lock on a file resource."""
        ok, err = self.rm.acquire(ResourceType.FILESYSTEM, "app.py", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        self.assertTrue(ok)
        self.assertIsNone(err)
        locks = self.rm.get_locks(worker_id="wkr-1")
        self.assertEqual(len(locks), 1)
        self.assertEqual(locks[0].mode, AccessMode.EXCLUSIVE)

    def test_02_exclusive_blocks_second_exclusive_lock(self):
        """Verify exclusive lock prevents second worker from acquiring exclusive lock."""
        self.rm.acquire(ResourceType.FILESYSTEM, "app.py", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        ok, err = self.rm.acquire(ResourceType.FILESYSTEM, "app.py", worker_id="wkr-2", mode=AccessMode.EXCLUSIVE)
        self.assertFalse(ok)
        self.assertIn("exclusively locked by worker 'wkr-1'", err)

    def test_03_shared_locks_allow_multiple_readers(self):
        """Verify shared mode allows concurrent locks across different workers."""
        ok1, _ = self.rm.acquire(ResourceType.FILESYSTEM, "docs.md", worker_id="wkr-1", mode=AccessMode.SHARED)
        ok2, _ = self.rm.acquire(ResourceType.FILESYSTEM, "docs.md", worker_id="wkr-2", mode=AccessMode.SHARED)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        locks = self.rm.get_locks(resource_type=ResourceType.FILESYSTEM)
        self.assertEqual(len(locks), 2)

    def test_04_exclusive_blocks_shared_request(self):
        """Verify existing exclusive lock prevents shared acquisition by another worker."""
        self.rm.acquire(ResourceType.FILESYSTEM, "data.db", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        ok, err = self.rm.acquire(ResourceType.FILESYSTEM, "data.db", worker_id="wkr-2", mode=AccessMode.SHARED)
        self.assertFalse(ok)
        self.assertIn("exclusively locked", err)

    def test_05_shared_blocks_exclusive_request(self):
        """Verify existing shared lock prevents exclusive acquisition by another worker."""
        self.rm.acquire(ResourceType.FILESYSTEM, "config.json", worker_id="wkr-1", mode=AccessMode.SHARED)
        ok, err = self.rm.acquire(ResourceType.FILESYSTEM, "config.json", worker_id="wkr-2", mode=AccessMode.EXCLUSIVE)
        self.assertFalse(ok)
        self.assertIn("currently held in shared mode", err)

    def test_06_reentrant_lock_same_worker(self):
        """Verify the same worker can re-acquire/refresh an exclusive lock on the same resource."""
        ok1, _ = self.rm.acquire(ResourceType.FILESYSTEM, "module.py", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        self.assertTrue(ok1)
        ok2, err2 = self.rm.acquire(ResourceType.FILESYSTEM, "module.py", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        self.assertTrue(ok2)
        self.assertIsNone(err2)
        # Should still be one lock entry for that worker
        locks = self.rm.get_locks(worker_id="wkr-1")
        self.assertEqual(len(locks), 1)

    def test_07_filesystem_path_normalization(self):
        """Verify relative and absolute paths resolve to the same normalized lock target."""
        p1 = "src/../src/file.py"
        p2 = "./src/file.py"
        ok1, _ = self.rm.acquire(ResourceType.FILESYSTEM, p1, worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        self.assertTrue(ok1)
        # Attempting p2 from another worker should detect conflict due to Path.resolve()
        ok2, err = self.rm.acquire(ResourceType.FILESYSTEM, p2, worker_id="wkr-2", mode=AccessMode.EXCLUSIVE)
        self.assertFalse(ok2)
        self.assertIn("exclusively locked", err)

    def test_08_gui_devices_strictly_enforce_exclusive_mode(self):
        """Verify KEYBOARD, MOUSE, and SCREEN enforce exclusive access mode automatically."""
        ok, _ = self.rm.acquire(ResourceType.KEYBOARD, "main_kb", worker_id="wkr-1", mode=AccessMode.SHARED)
        self.assertTrue(ok)
        locks = self.rm.get_locks(worker_id="wkr-1")
        self.assertEqual(locks[0].mode, AccessMode.EXCLUSIVE)

        # Second worker attempting mouse or screen also conflicts
        ok_m, err_m = self.rm.acquire(ResourceType.MOUSE, "main_mouse", worker_id="wkr-2", mode=AccessMode.SHARED)
        self.assertFalse(ok_m)
        self.assertIn("exclusively locked", err_m)

    def test_09_release_single_lock(self):
        """Verify releasing a lock allows a previously blocked worker to acquire."""
        self.rm.acquire(ResourceType.FILESYSTEM, "app.py", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)
        released = self.rm.release(ResourceType.FILESYSTEM, "app.py", worker_id="wkr-1")
        self.assertTrue(released)

        # wkr-2 can now acquire
        ok2, err2 = self.rm.acquire(ResourceType.FILESYSTEM, "app.py", worker_id="wkr-2", mode=AccessMode.EXCLUSIVE)
        self.assertTrue(ok2)
        self.assertIsNone(err2)

    def test_10_release_all_worker_locks(self):
        """Verify release_all frees all locks held across different resources for a worker."""
        self.rm.acquire(ResourceType.FILESYSTEM, "a.py", worker_id="wkr-1")
        self.rm.acquire(ResourceType.FILESYSTEM, "b.py", worker_id="wkr-1")
        self.rm.acquire(ResourceType.TERMINAL, "pty0", worker_id="wkr-1")
        self.assertEqual(len(self.rm.get_locks(worker_id="wkr-1")), 3)

        count = self.rm.release_all("wkr-1")
        self.assertEqual(count, 3)
        self.assertEqual(len(self.rm.get_locks(worker_id="wkr-1")), 0)

    def test_11_lock_timeout_and_expiration(self):
        """Verify lock expiration is detected accurately."""
        lock = ResourceLock(
            lock_id="lck-t1",
            resource_type=ResourceType.FILESYSTEM,
            resource_target="temp.txt",
            worker_id="wkr-1",
            mode=AccessMode.EXCLUSIVE,
            expires_at=time.time() - 1.0  # Already expired
        )
        self.assertTrue(lock.is_expired())

        valid_lock = ResourceLock(
            lock_id="lck-t2",
            resource_type=ResourceType.FILESYSTEM,
            resource_target="temp.txt",
            worker_id="wkr-1",
            mode=AccessMode.EXCLUSIVE,
            expires_at=time.time() + 60.0
        )
        self.assertFalse(valid_lock.is_expired())

    def test_12_orphan_lock_cleanup(self):
        """Verify cleanup_expired_locks purges expired locks automatically."""
        # Short timeout of 0.1 seconds
        self.rm.acquire(ResourceType.FILESYSTEM, "short.txt", worker_id="wkr-1", timeout=0.05)
        self.assertEqual(len(self.rm.get_locks()), 1)

        time.sleep(0.1)
        # Check conflict or acquisition clears expired lock
        purged = self.rm.cleanup_expired_locks()
        self.assertGreaterEqual(purged, 1)
        self.assertEqual(len(self.rm.get_locks()), 0)

        # New worker can acquire immediately
        ok, _ = self.rm.acquire(ResourceType.FILESYSTEM, "short.txt", worker_id="wkr-2")
        self.assertTrue(ok)

    def test_13_check_conflict_without_acquiring(self):
        """Verify check_conflict inspects lock table without side effects."""
        self.rm.acquire(ResourceType.CYBER_TARGET, "127.0.0.1", worker_id="wkr-1", mode=AccessMode.EXCLUSIVE)

        conflict, reason = self.rm.check_conflict(ResourceType.CYBER_TARGET, "127.0.0.1", AccessMode.EXCLUSIVE, requesting_worker_id="wkr-2")
        self.assertTrue(conflict)
        self.assertIn("exclusively locked", reason)

        # Same worker should not conflict with itself
        conflict_self, _ = self.rm.check_conflict(ResourceType.CYBER_TARGET, "127.0.0.1", AccessMode.EXCLUSIVE, requesting_worker_id="wkr-1")
        self.assertFalse(conflict_self)

    def test_14_resource_lock_serialization(self):
        """Verify ResourceLock to_dict and from_dict roundtrip."""
        lock = ResourceLock(
            lock_id="lck-ser-1",
            resource_type=ResourceType.BLENDER,
            resource_target="scene_01",
            worker_id="wkr-blender",
            mode=AccessMode.EXCLUSIVE,
            expires_at=123456789.0,
            project_id="proj-3d"
        )
        d = lock.to_dict()
        restored = ResourceLock.from_dict(d)
        self.assertEqual(restored.lock_id, "lck-ser-1")
        self.assertEqual(restored.resource_type, ResourceType.BLENDER)
        self.assertEqual(restored.worker_id, "wkr-blender")
        self.assertEqual(restored.project_id, "proj-3d")

    def test_15_get_locks_filtered_by_resource_type(self):
        """Verify get_locks filters correctly by ResourceType."""
        self.rm.acquire(ResourceType.FILESYSTEM, "f1.py", worker_id="wkr-1")
        self.rm.acquire(ResourceType.CYBER_TARGET, "target-1", worker_id="wkr-2")

        fs_locks = self.rm.get_locks(resource_type=ResourceType.FILESYSTEM)
        self.assertEqual(len(fs_locks), 1)
        self.assertEqual(fs_locks[0].resource_type, ResourceType.FILESYSTEM)

        cyber_locks = self.rm.get_locks(resource_type=ResourceType.CYBER_TARGET)
        self.assertEqual(len(cyber_locks), 1)
        self.assertEqual(cyber_locks[0].resource_type, ResourceType.CYBER_TARGET)

    def test_16_get_locks_filtered_by_project_id(self):
        """Verify get_locks filters correctly by project_id."""
        self.rm.acquire(ResourceType.FILESYSTEM, "p1.py", worker_id="wkr-1", project_id="proj-alpha")
        self.rm.acquire(ResourceType.FILESYSTEM, "p2.py", worker_id="wkr-2", project_id="proj-beta")

        alpha_locks = self.rm.get_locks(project_id="proj-alpha")
        self.assertEqual(len(alpha_locks), 1)
        self.assertEqual(alpha_locks[0].project_id, "proj-alpha")

    def test_17_read_only_access_mode(self):
        """Verify READ_ONLY locks act as shared readers without blocking other readers."""
        ok1, _ = self.rm.acquire(ResourceType.FILESYSTEM, "manual.pdf", worker_id="w1", mode=AccessMode.READ_ONLY)
        ok2, _ = self.rm.acquire(ResourceType.FILESYSTEM, "manual.pdf", worker_id="w2", mode=AccessMode.READ_ONLY)
        self.assertTrue(ok1)
        self.assertTrue(ok2)

        # Exclusive request from w3 still blocked
        ok3, err3 = self.rm.acquire(ResourceType.FILESYSTEM, "manual.pdf", worker_id="w3", mode=AccessMode.EXCLUSIVE)
        self.assertFalse(ok3)

    def test_18_release_nonexistent_lock(self):
        """Verify release on unheld lock returns False gracefully."""
        self.assertFalse(self.rm.release(ResourceType.FILESYSTEM, "unheld.py", worker_id="wkr-1"))

    def test_19_invalid_worker_or_target_rejection(self):
        """Verify acquire rejects empty worker_id or empty target."""
        ok1, err1 = self.rm.acquire(ResourceType.FILESYSTEM, "target.txt", worker_id="")
        self.assertFalse(ok1)
        self.assertIn("worker_id cannot be empty", err1)

        ok2, err2 = self.rm.acquire(ResourceType.FILESYSTEM, "", worker_id="wkr-1")
        self.assertFalse(ok2)
        self.assertIn("resource target cannot be empty", err2)

    def test_20_clear_manager(self):
        """Verify clear() purges all locks across all resources."""
        self.rm.acquire(ResourceType.FILESYSTEM, "f1.py", worker_id="w1")
        self.rm.acquire(ResourceType.TERMINAL, "t1", worker_id="w2")
        self.rm.clear()
        self.assertEqual(len(self.rm.get_locks()), 0)


if __name__ == "__main__":
    unittest.main()
