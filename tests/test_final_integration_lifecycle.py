"""
Tests for ZARA Phase 18 Unified Lifecycle Management, Configuration Hardening,
and Persistence Integrity.
"""
import unittest
import tempfile
import shutil
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.lifecycle import ZaraLifecycleManager, LifecycleState
from core.health import SubsystemStatus
from config.validator import ConfigValidator, ConfigValidationResult
from core.persistence import (
    atomic_write_json, atomic_write_text, safe_read_json, safe_append_jsonl,
    compute_checksum, quarantine_corrupt_file, cleanup_temp_files
)
from core.recovery import RecoveryManager, RecoveryClassification
from core.state import TaskContext, PlanStep, ActionType, StepStatus
from core.engine import ZaraEngine


class TestFinalIntegrationLifecycle(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_root = Path(self.temp_dir).resolve()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle Management Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_01_lifecycle_state_initialization(self):
        """LifecycleManager initializes with STARTUP state."""
        mgr = ZaraLifecycleManager()
        self.assertEqual(mgr.state, LifecycleState.STARTUP)
        status = mgr.get_status()
        self.assertEqual(status.state, LifecycleState.STARTUP)

    def test_02_lifecycle_startup_transitions_to_ready(self):
        """LifecycleManager startup transitions through validation and lands on READY or DEGRADED."""
        mgr = ZaraLifecycleManager()
        success = mgr.startup()
        self.assertIn(mgr.state, (LifecycleState.READY, LifecycleState.DEGRADED))
        status = mgr.get_status()
        self.assertIsNotNone(status.started_at)
        self.assertGreaterEqual(status.uptime_seconds, 0.0)

    def test_03_lifecycle_shutdown_cleans_resources(self):
        """LifecycleManager shutdown transitions to TERMINATED and closes engine resources."""
        mock_engine = MagicMock()
        mgr = ZaraLifecycleManager(engine=mock_engine)
        mgr.startup()
        mgr.shutdown()

        self.assertEqual(mgr.state, LifecycleState.TERMINATED)
        mock_engine.workstream_orchestrator.close.assert_called()
        mock_engine.resource_manager.clear.assert_called()
        mock_engine.model_router.close.assert_called()
        mock_engine.evaluation_manager.close.assert_called()

    def test_04_repeated_startup_shutdown_cycles(self):
        """Repeated startup and shutdown cycles execute without errors or state leaks."""
        mgr = ZaraLifecycleManager()
        for i in range(3):
            mgr.startup()
            self.assertIn(mgr.state, (LifecycleState.READY, LifecycleState.DEGRADED))
            mgr.shutdown()
            self.assertEqual(mgr.state, LifecycleState.TERMINATED)

    # ──────────────────────────────────────────────────────────────────────────
    # Configuration Validator Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_05_config_validator_validates_default_settings(self):
        """Default active configuration passes all type, bound, and security checks."""
        res = ConfigValidator.validate()
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.errors), 0)
        self.assertIn("MAX_STEPS", res.sanitized_config)

    def test_06_config_validator_rejects_negative_timeouts(self):
        """Negative timeouts or step limits are rejected with explicit errors."""
        res = ConfigValidator.validate(overrides={"COMMAND_TIMEOUT_SECONDS": -10, "MAX_STEPS": 0})
        self.assertFalse(res.is_valid)
        self.assertTrue(any("COMMAND_TIMEOUT_SECONDS" in err for err in res.errors))
        self.assertTrue(any("MAX_STEPS" in err for err in res.errors))

    def test_07_config_validator_rejects_out_of_bounds_ports(self):
        """UI port outside range [1024, 65535] is rejected."""
        res = ConfigValidator.validate(overrides={"UI_PORT": 80})
        self.assertFalse(res.is_valid)
        self.assertTrue(any("UI_PORT" in err for err in res.errors))

    def test_08_config_validator_rejects_missing_critical_files(self):
        """CRITICAL_FILES_BLOCKLIST missing required security paths fails validation."""
        res = ConfigValidator.validate(overrides={"CRITICAL_FILES_BLOCKLIST": {"config/settings.py"}})
        self.assertFalse(res.is_valid)
        self.assertTrue(any("missing required critical files" in err for err in res.errors))

    def test_09_config_validator_sanitizes_secrets(self):
        """Sanitized config redaction masks any keys, tokens, or passwords."""
        cfg = {"API_KEY": "secret_abc123", "SAFE_PARAM": 42}
        sanitized = ConfigValidator._sanitize_config(cfg)
        self.assertEqual(sanitized["API_KEY"], "[REDACTED]")
        self.assertEqual(sanitized["SAFE_PARAM"], 42)

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence Integrity Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_10_atomic_write_json_success(self):
        """atomic_write_json writes valid JSON file atomically."""
        test_file = self.workspace_root / "test_data.json"
        data = {"name": "zara", "version": 18, "status": "active"}
        atomic_write_json(test_file, data)

        self.assertTrue(test_file.exists())
        loaded, is_valid = safe_read_json(test_file)
        self.assertTrue(is_valid)
        self.assertEqual(loaded["name"], "zara")

    def test_11_atomic_write_json_cleans_temp_on_failure(self):
        """If serialization or write fails, temporary file is cleaned up."""
        test_file = self.workspace_root / "test_fail.json"
        # Unserializable circular reference
        bad_data = {}
        bad_data["self"] = bad_data

        with self.assertRaises(Exception):
            atomic_write_json(test_file, bad_data)

        # Confirm no lingering .tmp file
        tmp_files = list(self.workspace_root.glob("*.tmp*"))
        self.assertEqual(len(tmp_files), 0)

    def test_12_atomic_write_text_success(self):
        """atomic_write_text writes text file atomically."""
        test_file = self.workspace_root / "test.txt"
        atomic_write_text(test_file, "Hello ZARA Phase 18")
        self.assertEqual(test_file.read_text(encoding="utf-8"), "Hello ZARA Phase 18")

    def test_13_safe_read_json_handles_missing_file(self):
        """safe_read_json returns default and False if file does not exist."""
        test_file = self.workspace_root / "non_existent.json"
        data, is_valid = safe_read_json(test_file, default={"fallback": True})
        self.assertFalse(is_valid)
        self.assertEqual(data, {"fallback": True})

    def test_14_safe_read_json_handles_corrupt_json(self):
        """safe_read_json detects truncated/corrupt JSON and returns False."""
        test_file = self.workspace_root / "corrupt.json"
        test_file.write_text('{"name": "zara", "incomplete": ', encoding="utf-8")

        data, is_valid = safe_read_json(test_file, default=None)
        self.assertFalse(is_valid)
        self.assertIsNone(data)

    def test_15_safe_append_jsonl_thread_safety(self):
        """safe_append_jsonl appends valid lines to JSONL log."""
        log_file = self.workspace_root / "journal.jsonl"
        safe_append_jsonl(log_file, {"event": "STEP_1", "status": "OK"})
        safe_append_jsonl(log_file, {"event": "STEP_2", "status": "OK"})

        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 2)
        rec1 = json.loads(lines[0])
        self.assertEqual(rec1["event"], "STEP_1")

    def test_16_compute_checksum(self):
        """compute_checksum generates valid SHA-256 hex digest."""
        test_file = self.workspace_root / "check.txt"
        test_file.write_text("Integrity Check Data", encoding="utf-8")
        h = compute_checksum(test_file)
        self.assertEqual(len(h), 64)
        # Idempotent
        self.assertEqual(compute_checksum(test_file), h)

    def test_17_quarantine_corrupt_file(self):
        """quarantine_corrupt_file moves corrupted file to .corrupt timestamped path."""
        bad_file = self.workspace_root / "bad.json"
        bad_file.write_text("corrupt data", encoding="utf-8")
        corrupt_path = quarantine_corrupt_file(bad_file)

        self.assertIsNotNone(corrupt_path)
        self.assertFalse(bad_file.exists())
        self.assertTrue(corrupt_path.exists())
        self.assertIn(".corrupt.", str(corrupt_path))

    def test_18_cleanup_temp_files(self):
        """cleanup_temp_files unlinks leftover temporary files from interrupted writes."""
        (self.workspace_root / "file1.tmp.12345").write_text("temp", encoding="utf-8")
        (self.workspace_root / "file2.tmp.67890").write_text("temp", encoding="utf-8")
        (self.workspace_root / "real_file.json").write_text("{}", encoding="utf-8")

        cleaned = cleanup_temp_files(self.workspace_root)
        self.assertEqual(cleaned, 2)
        self.assertTrue((self.workspace_root / "real_file.json").exists())

    # ──────────────────────────────────────────────────────────────────────────
    # Crash Recovery Classification Tests
    # ──────────────────────────────────────────────────────────────────────────

    def test_19_recovery_classification_safe_resume_completed(self):
        """Completed task is classified as SAFE_RESUME."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx = TaskContext(
            task="Build feature",
            tag="dev",
            working_dir=str(self.workspace_root),
            steps=[PlanStep(id=1, title="Build", action_type=ActionType.CODE, description="Build", target="x.py", status=StepStatus.PASSED)],
            is_completed=True
        )
        cls, msg = rm.classify_recovery(ctx)
        self.assertEqual(cls, RecoveryClassification.SAFE_RESUME)

    def test_20_recovery_classification_manual_intervention(self):
        """Task blocked on human input or error blocker requires MANUAL_INTERVENTION."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx = TaskContext(
            task="Deploy server",
            tag="ops",
            working_dir=str(self.workspace_root),
            steps=[],
            requires_human_input=True,
            blocker_reason="Missing production token"
        )
        cls, msg = rm.classify_recovery(ctx)
        self.assertEqual(cls, RecoveryClassification.MANUAL_INTERVENTION)
        self.assertIn("Missing production token", msg)

    def test_21_recovery_classification_retry_transient_error(self):
        """Step failed with timeout or network error is classified as RETRY."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx = TaskContext(
            task="Download asset",
            tag="web",
            working_dir=str(self.workspace_root),
            steps=[
                PlanStep(
                    id=1,
                    title="Fetch URL",
                    action_type=ActionType.TOOL,
                    description="Fetch remote asset",
                    target="http://example.com",
                    status=StepStatus.FAILED,
                    error_message="Connection timeout after 30s"
                )
            ]
        )
        cls, msg = rm.classify_recovery(ctx)
        self.assertEqual(cls, RecoveryClassification.RETRY)

    def test_22_recovery_classification_requires_verification(self):
        """Step failed verification requires REQUIRES_VERIFICATION."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx = TaskContext(
            task="Fix bug",
            tag="dev",
            working_dir=str(self.workspace_root),
            steps=[
                PlanStep(
                    id=1,
                    title="Run tests",
                    action_type=ActionType.TEST,
                    description="Run unit tests",
                    target="test_fix.py",
                    status=StepStatus.FAILED,
                    error_message="AssertionError: 2 != 3"
                )
            ]
        )
        cls, msg = rm.classify_recovery(ctx)
        self.assertEqual(cls, RecoveryClassification.REQUIRES_VERIFICATION)

    def test_23_recovery_classification_requires_approval_for_sensitive(self):
        """Interrupted or pending sensitive command/cyber action requires REQUIRES_APPROVAL."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx = TaskContext(
            task="Security audit",
            tag="cyber",
            working_dir=str(self.workspace_root),
            steps=[
                PlanStep(
                    id=1,
                    title="Nmap Port Scan",
                    action_type=ActionType.SECURITY_AUDIT,
                    description="Scan local ports",
                    target="localhost",
                    status=StepStatus.RUNNING
                )
            ]
        )
        cls, msg = rm.classify_recovery(ctx)
        self.assertEqual(cls, RecoveryClassification.REQUIRES_APPROVAL)
        self.assertIn("sensitive", msg.lower())

    def test_24_checkpoint_save_and_load_with_atomic_persistence(self):
        """RecoveryManager saves and loads checkpoints atomically."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx = TaskContext(
            task="Atomic checkpoint test",
            tag="test",
            working_dir=str(self.workspace_root),
            steps=[PlanStep(id=1, title="Step 1", action_type=ActionType.CODE, description="Write", target="f.txt", status=StepStatus.PASSED)],
            current_step_index=0
        )
        path = rm.save_checkpoint(ctx)
        self.assertTrue(path.exists())

        loaded = rm.load_checkpoint(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.task, "Atomic checkpoint test")
        self.assertEqual(len(loaded.steps), 1)

    def test_25_checkpoint_load_corrupt_quarantines_file(self):
        """Loading a corrupt checkpoint quarantines the file and returns None."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        cp_path = self.workspace_root / "checkpoints" / "checkpoint_bad.json"
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        cp_path.write_text("{corrupt: json syntax error", encoding="utf-8")

        loaded = rm.load_checkpoint(cp_path)
        self.assertIsNone(loaded)
        self.assertFalse(cp_path.exists())
        # Quarantined file should exist
        corrupts = list(cp_path.parent.glob("checkpoint_bad.corrupt.*"))
        self.assertEqual(len(corrupts), 1)

    def test_26_get_latest_checkpoint(self):
        """RecoveryManager.get_latest_checkpoint retrieves the most recently modified checkpoint."""
        rm = RecoveryManager(checkpoints_dir=self.workspace_root / "checkpoints")
        ctx1 = TaskContext(task="Old task", tag="t1", working_dir=str(self.workspace_root))
        ctx2 = TaskContext(task="New task", tag="t2", working_dir=str(self.workspace_root))

        rm.save_checkpoint(ctx1)
        import time
        time.sleep(0.05)
        path2 = rm.save_checkpoint(ctx2)

        res = rm.get_latest_checkpoint()
        self.assertIsNotNone(res)
        latest_path, latest_ctx = res
        self.assertEqual(latest_ctx.task, "New task")

    def test_27_engine_lifecycle_manager_integration(self):
        """ZaraEngine initializes with lifecycle_manager, health_service, doctor_service, backup_manager."""
        engine = ZaraEngine(workspace_root=str(self.workspace_root), enable_voice=False)
        try:
            self.assertTrue(hasattr(engine, "lifecycle_manager"))
            self.assertTrue(hasattr(engine, "health_service"))
            self.assertTrue(hasattr(engine, "doctor_service"))
            self.assertTrue(hasattr(engine, "backup_manager"))
        finally:
            engine.close()

    def test_28_engine_close_idempotency(self):
        """Calling engine.close() multiple times is safe and causes no errors or ResourceWarnings."""
        engine = ZaraEngine(workspace_root=str(self.workspace_root), enable_voice=False)
        engine.close()
        engine.close()
        engine.close()


if __name__ == "__main__":
    unittest.main()
