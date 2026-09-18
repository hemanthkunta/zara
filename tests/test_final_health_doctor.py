"""
Tests for ZARA Phase 18 Global Health Service, Environment Doctor,
and Safe Backup & Restore Operations.
"""
import unittest
import tempfile
import shutil
import tarfile
import json
import os
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.health import GlobalHealthService, SubsystemStatus, SubsystemHealth, SystemHealthReport
from core.doctor import EnvironmentDoctor, DependencyCategory, DependencyStatus, DoctorReport
from core.backup import BackupManager
from core.engine import ZaraEngine


class TestFinalHealthDoctor(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_root = Path(self.temp_dir).resolve()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Global Health Service Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_global_health_check_all_structure(self):
        """GlobalHealthService.check_all() returns a report containing all 16 subsystems."""
        svc = GlobalHealthService()
        rep = svc.check_all()

        self.assertIsInstance(rep, SystemHealthReport)
        self.assertEqual(rep.total_count, 16)
        expected_subs = {
            "Core", "Memory", "World Model", "Planner", "Workers",
            "Model Router", "Event Bus", "Scheduler", "Voice", "Vision",
            "Browser", "Cyber Lab", "Blender", "Workspace", "Learning", "UI"
        }
        self.assertEqual(set(rep.components.keys()), expected_subs)
        self.assertIn(rep.overall, (SubsystemStatus.HEALTHY, SubsystemStatus.READY, SubsystemStatus.DEGRADED, SubsystemStatus.FAILED))

    def test_02_global_health_subsystem_status_values(self):
        """All component statuses belong to SubsystemStatus enum."""
        svc = GlobalHealthService()
        rep = svc.check_all()
        for name, sub in rep.components.items():
            self.assertIsInstance(sub.status, SubsystemStatus)
            self.assertGreaterEqual(sub.latency_ms, 0.0)
            self.assertTrue(len(sub.message) > 0)

    def test_03_core_probe_healthy_on_writable_workspace(self):
        """Core probe returns HEALTHY when workspace root exists and is writable."""
        mock_eng = MagicMock()
        mock_eng.workspace_root = self.workspace_root
        svc = GlobalHealthService(engine=mock_eng)
        h = svc._check_core()
        self.assertEqual(h.status, SubsystemStatus.HEALTHY)

    def test_04_core_probe_fails_on_missing_workspace(self):
        """Core probe returns FAILED when workspace root does not exist."""
        mock_eng = MagicMock()
        mock_eng.workspace_root = self.workspace_root / "does_not_exist"
        svc = GlobalHealthService(engine=mock_eng)
        h = svc._check_core()
        self.assertEqual(h.status, SubsystemStatus.FAILED)

    def test_05_memory_probe_healthy_with_store(self):
        """Memory probe returns HEALTHY and includes memory statistics."""
        svc = GlobalHealthService()
        h = svc._check_memory()
        self.assertIn(h.status, (SubsystemStatus.HEALTHY, SubsystemStatus.READY))

    def test_06_world_model_probe_reflects_perception(self):
        """World Model probe reports perception readiness."""
        svc = GlobalHealthService()
        h = svc._check_world_model()
        self.assertIn(h.status, (SubsystemStatus.HEALTHY, SubsystemStatus.READY))

    def test_07_planner_probe_reports_healthy(self):
        """Planner probe reports planning engine operational status."""
        svc = GlobalHealthService()
        h = svc._check_planner()
        self.assertIn(h.status, (SubsystemStatus.HEALTHY, SubsystemStatus.READY))

    def test_08_workers_probe_reports_lock_counts(self):
        """Workers probe reports active locks and worker state."""
        mock_eng = MagicMock()
        mock_rm = MagicMock()
        mock_rm.list_locks.return_value = ["lock1", "lock2"]
        mock_eng.resource_manager = mock_rm
        svc = GlobalHealthService(engine=mock_eng)
        h = svc._check_workers()
        self.assertEqual(h.status, SubsystemStatus.HEALTHY)
        self.assertEqual(h.details["active_locks"], 2)

    def test_09_model_router_probe_reports_providers(self):
        """Model Router probe lists registered providers."""
        svc = GlobalHealthService()
        h = svc._check_model_router()
        self.assertEqual(h.status, SubsystemStatus.HEALTHY)
        self.assertIn("mock", h.details.get("providers", []))

    def test_10_event_bus_probe_reports_subscribers(self):
        """Event Bus probe reports operational bus."""
        svc = GlobalHealthService()
        h = svc._check_event_bus()
        self.assertIn(h.status, (SubsystemStatus.HEALTHY, SubsystemStatus.READY))

    def test_11_scheduler_probe_reports_jobs(self):
        """Scheduler probe reports job count."""
        mock_eng = MagicMock()
        mock_sched = MagicMock()
        mock_sched.jobs = {"job1": MagicMock()}
        mock_eng.scheduler = mock_sched
        svc = GlobalHealthService(engine=mock_eng)
        h = svc._check_scheduler()
        self.assertEqual(h.status, SubsystemStatus.HEALTHY)
        self.assertEqual(h.details["jobs"], 1)

    def test_12_voice_probe_reports_status(self):
        """Voice probe reports ready or disabled according to configuration."""
        svc = GlobalHealthService()
        h = svc._check_voice()
        self.assertIn(h.status, (SubsystemStatus.READY, SubsystemStatus.DISABLED))

    def test_13_vision_probe_reports_status(self):
        """Vision probe reports perception readiness."""
        svc = GlobalHealthService()
        h = svc._check_vision()
        self.assertEqual(h.status, SubsystemStatus.READY)

    def test_14_browser_probe_reports_status(self):
        """Browser probe reports autonomous research readiness."""
        svc = GlobalHealthService()
        h = svc._check_browser()
        self.assertEqual(h.status, SubsystemStatus.READY)

    def test_15_cyber_lab_probe_checks_security_scope(self):
        """Cyber Lab probe checks scope allowlist file."""
        svc = GlobalHealthService()
        h = svc._check_cyber_lab()
        self.assertIn(h.status, (SubsystemStatus.READY, SubsystemStatus.DEGRADED))

    def test_16_blender_probe_detects_binary_or_reports_degraded(self):
        """Blender probe returns READY if binary is found or DEGRADED if absent."""
        svc = GlobalHealthService()
        h = svc._check_blender()
        self.assertIn(h.status, (SubsystemStatus.READY, SubsystemStatus.DEGRADED))

    def test_17_workspace_probe_reports_manifest_access(self):
        """Workspace probe reports accessible state."""
        svc = GlobalHealthService()
        h = svc._check_workspace()
        self.assertEqual(h.status, SubsystemStatus.HEALTHY)

    def test_18_learning_probe_checks_strategy_file(self):
        """Learning probe checks strategy registry and evaluation storage."""
        svc = GlobalHealthService()
        h = svc._check_learning()
        self.assertIn(h.status, (SubsystemStatus.HEALTHY, SubsystemStatus.READY))

    def test_19_ui_probe_checks_port_binding(self):
        """UI probe tests port responsiveness or bind availability."""
        svc = GlobalHealthService()
        h = svc._check_ui()
        self.assertIn(h.status, (SubsystemStatus.HEALTHY, SubsystemStatus.READY))

    def test_20_overall_health_calculation_degraded_vs_failed(self):
        """Critical component failure forces FAILED; non-critical degradation yields DEGRADED."""
        svc = GlobalHealthService()
        with patch.object(svc, "_check_core", return_value=SubsystemHealth(name="Core", status=SubsystemStatus.FAILED, message="Disk error")):
            rep = svc.check_all()
            self.assertEqual(rep.overall, SubsystemStatus.FAILED)

        with patch.object(svc, "_check_core", return_value=SubsystemHealth(name="Core", status=SubsystemStatus.HEALTHY, message="OK")), \
             patch.object(svc, "_check_blender", return_value=SubsystemHealth(name="Blender", status=SubsystemStatus.DEGRADED, message="No binary")):
            rep = svc.check_all()
            self.assertEqual(rep.overall, SubsystemStatus.DEGRADED)

    # ──────────────────────────────────────────────────────────────────────────
    # Environment Doctor Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_21_environment_doctor_python_version_check(self):
        """EnvironmentDoctor validates Python version >= 3.10."""
        rep = EnvironmentDoctor.run_diagnostics(self.workspace_root)
        self.assertIsInstance(rep, DoctorReport)
        py_check = next((c for c in rep.checks if c.name == "Python Runtime"), None)
        self.assertIsNotNone(py_check)
        self.assertEqual(py_check.status, DependencyStatus.AVAILABLE)

    def test_22_environment_doctor_git_check(self):
        """EnvironmentDoctor detects Git installation."""
        rep = EnvironmentDoctor.run_diagnostics(self.workspace_root)
        git_check = next((c for c in rep.checks if c.name == "Git Version Control"), None)
        self.assertIsNotNone(git_check)
        self.assertEqual(git_check.category, DependencyCategory.REQUIRED)

    def test_23_environment_doctor_sqlite_check(self):
        """EnvironmentDoctor verifies SQLite3 operational status."""
        rep = EnvironmentDoctor.run_diagnostics(self.workspace_root)
        sql_check = next((c for c in rep.checks if c.name == "SQLite3 Database"), None)
        self.assertIsNotNone(sql_check)
        self.assertEqual(sql_check.status, DependencyStatus.AVAILABLE)

    def test_24_environment_doctor_security_scope_check(self):
        """EnvironmentDoctor verifies Cyber Lab Scope Allowlist."""
        rep = EnvironmentDoctor.run_diagnostics(self.workspace_root)
        scope_check = next((c for c in rep.checks if c.name == "Cyber Lab Scope Allowlist"), None)
        self.assertIsNotNone(scope_check)
        self.assertIn(scope_check.status, (DependencyStatus.AVAILABLE, DependencyStatus.WARNING))

    def test_25_environment_doctor_no_secrets_in_report(self):
        """DoctorReport never exposes actual API keys or credentials."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSySecretRealKey12345678901234"}):
            rep = EnvironmentDoctor.run_diagnostics(self.workspace_root)
            rep_str = json.dumps(rep.to_dict())
            self.assertNotIn("AIzaSySecretRealKey12345678901234", rep_str)

    # ──────────────────────────────────────────────────────────────────────────
    # Safe Backup & Restore Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_26_backup_manager_create_valid_tar_gz(self):
        """BackupManager creates valid compressed archive with manifest and checksums."""
        bm = BackupManager(backups_dir=self.workspace_root / "backups", base_dir=self.workspace_root)
        # Create mock file in memory dir
        (self.workspace_root / "memory").mkdir(parents=True, exist_ok=True)
        (self.workspace_root / "memory" / "zara_log.md").write_text("# ZARA Lessons", encoding="utf-8")

        archive = bm.create_backup()
        self.assertTrue(archive.exists())
        self.assertTrue(str(archive).endswith(".tar.gz"))

        # Inspect archive manifest
        with tarfile.open(archive, "r:gz") as tar:
            names = tar.getnames()
            self.assertIn("backup_manifest.json", names)
            manifest_file = tar.extractfile("backup_manifest.json")
            manifest = json.loads(manifest_file.read().decode("utf-8"))
            self.assertEqual(manifest["version"], "1.0")

    def test_27_backup_manager_restore_safe_extraction(self):
        """BackupManager restores archive safely and records pre-restore checkpoint."""
        bm = BackupManager(backups_dir=self.workspace_root / "backups", base_dir=self.workspace_root)
        (self.workspace_root / "memory").mkdir(parents=True, exist_ok=True)
        (self.workspace_root / "memory" / "zara_log.md").write_text("# Initial Lessons", encoding="utf-8")

        archive = bm.create_backup()

        # Modify original file
        (self.workspace_root / "memory" / "zara_log.md").write_text("# Modified Lessons", encoding="utf-8")

        # Restore from backup
        res = bm.restore_backup(archive)
        self.assertTrue(res["success"])
        self.assertEqual((self.workspace_root / "memory" / "zara_log.md").read_text(encoding="utf-8"), "# Initial Lessons")
        self.assertIsNotNone(res.get("pre_restore_backup"))

    def test_28_backup_manager_restore_blocks_path_traversal(self):
        """BackupManager refuses to extract archives containing path traversal ('../') paths."""
        bm = BackupManager(backups_dir=self.workspace_root / "backups", base_dir=self.workspace_root)
        evil_tar = self.workspace_root / "backups" / "evil.tar.gz"
        evil_tar.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(evil_tar, "w:gz") as tar:
            ti = tarfile.TarInfo(name="../escaped.txt")
            data = b"malicious escape"
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))

        with self.assertRaises(ValueError) as cm:
            bm.restore_backup(evil_tar, create_pre_restore_checkpoint=False)
        self.assertIn("path traversal", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
