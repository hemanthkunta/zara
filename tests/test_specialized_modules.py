"""
Unit tests for ZARA Specialized Subsystems (Git, Blender, Research, Recovery, Security Lab).
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from modules.git_tools import GitModule
from modules.blender import BlenderModule
from modules.research import ResearchModule
from modules.security import SecurityModule, ScopeViolationError
from core.recovery import RecoveryManager
from core.state import TaskContext, PlanStep, ActionType, StepStatus
from core.observability import AuditLogger
from modules.verification import VerificationEngine

class TestSpecializedModules(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_spec_test_")
        self.workspace = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_git_module(self):
        git = GitModule(self.workspace)
        status = git.status()
        self.assertIsInstance(status, dict)

    def test_blender_module_script_generation(self):
        scripts_dir = self.workspace / "blender_scripts"
        blender = BlenderModule(scripts_dir)

        script_path = blender.generate_scene_script(scene_type="monkey", mesh_name="TestSuzanne")
        self.assertTrue(Path(script_path).exists())
        content = Path(script_path).read_text()
        self.assertIn("TestSuzanne", content)
        self.assertIn("primitive_monkey_add", content)

    def test_research_module_synthesis(self):
        research = ResearchModule()
        report = research.search_and_synthesize("Python programming")
        self.assertIsInstance(report, dict)
        self.assertEqual(report["query"], "Python programming")
        self.assertIn("verified_facts", report)
        self.assertIn("zara_inference", report)

    def test_recovery_checkpoint_and_load(self):
        recovery = RecoveryManager(self.workspace / "checkpoints")

        ctx = TaskContext(
            task="Build auth service",
            tag="auth",
            working_dir=str(self.workspace),
            steps=[
                PlanStep(
                    id=1,
                    title="Write auth.py",
                    action_type=ActionType.CODE,
                    description="Create auth logic",
                    target="auth.py",
                    payload={"file_path": "auth.py", "content": "# auth\n"},
                    success_condition="File written",
                    status=StepStatus.PASSED
                )
            ]
        )

        ckp_path = recovery.save_checkpoint(ctx)
        self.assertTrue(ckp_path.exists())

        loaded_ctx = recovery.load_checkpoint(ckp_path)
        self.assertIsNotNone(loaded_ctx)
        self.assertEqual(loaded_ctx.task, "Build auth service")
        self.assertEqual(len(loaded_ctx.steps), 1)
        self.assertEqual(loaded_ctx.steps[0].status, StepStatus.PASSED)

    def test_secret_scrubber(self):
        dirty = "My API key is sk-1234567890abcdef1234567890 and password: 'SuperSecretPassword123'"
        clean = AuditLogger.scrub_secrets(dirty)
        self.assertNotIn("sk-1234567890abcdef1234567890", clean)
        self.assertNotIn("SuperSecretPassword123", clean)
        self.assertIn("[REDACTED", clean)

    def test_verification_engine(self):
        verif = VerificationEngine(self.workspace)
        # Test command exit code verification
        ev1 = verif.verify_command("echo 'ZARA-EVIDENCE'")
        self.assertTrue(ev1.verified)
        self.assertEqual(ev1.exit_code, 0)
        self.assertGreater(len(ev1.output_hash), 10)

        # Test Python syntax verification
        test_py = self.workspace / "test.py"
        test_py.write_text("def test(): return True\n")
        ev2 = verif.verify_python_syntax("test.py")
        self.assertTrue(ev2.verified)

    def test_security_lab_authorized_scan(self):
        scope_file = self.workspace / "scope.json"
        scope_file.write_text('{"allowed_hosts": ["127.0.0.1", "localhost"]}')
        sec = SecurityModule(scope_file)

        # Authorized scan on 127.0.0.1
        findings = sec.run_authorized_port_scan("127.0.0.1", ports=[80, 8080])
        self.assertIn("results", findings)
        self.assertEqual(findings["target"], "127.0.0.1")

        # Prohibited scan on unauthorized external host
        with self.assertRaises(ScopeViolationError):
            sec.run_authorized_port_scan("external-target-test.com")

if __name__ == "__main__":
    unittest.main()
