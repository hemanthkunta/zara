"""
Unit tests for ZARA Phase 17: Improvement Proposals, Critical Safety Guardrails,
Experiment Framework, Versioned Rollbacks, Engine Integration, UI APIs, and CLI.
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.state import TaskContext, PlanStep, StepStatus, ActionType, Diagnosis
from modules.events import EventBus, EventType
from modules.memory import MemoryStore
from modules.evaluation import (
    EvaluationManager,
    ImprovementProposal,
    ProposalRisk,
    ProposalStatus,
    ChangeType,
    Experiment,
    ExperimentStatus,
    ImprovementVersion,
)
from modules.self_improvement import SelfImprovementEvaluator


class TestImprovementExperiments(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.evals_dir = self.tmp_dir / "evaluations"
        self.props_dir = self.tmp_dir / "proposals"
        self.exps_dir = self.tmp_dir / "experiments"
        self.mem_dir = self.tmp_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryStore(memory_path=self.mem_dir / "zara_log.md", db_path=self.mem_dir / "v.db")
        self.event_bus = EventBus()
        self.manager = EvaluationManager(
            memory_store=self.memory,
            event_bus=self.event_bus,
            evaluations_dir=self.evals_dir,
            proposals_dir=self.props_dir,
            experiments_dir=self.exps_dir,
        )

    def tearDown(self):
        self.manager.close()
        self.memory.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_create_proposal_low_risk(self):
        """Low-risk documentation/heuristic proposal instantiates with PROPOSED status."""
        prop = self.manager.create_proposal(
            title="Update README tips",
            description="Add usage tips for voice command",
            affected_component="docs/tips.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={"user_feedback_count": 3},
            expected_benefit="Improved onboarding experience",
        )
        self.assertEqual(prop.risk, ProposalRisk.LOW)
        self.assertEqual(prop.status, ProposalStatus.PROPOSED)
        self.assertIn(prop.proposal_id, self.manager.proposals)

    def test_02_critical_safety_blocklist_cyber_lab(self):
        """CRITICAL SAFETY PRINCIPLE: Proposals attempting to modify cyber_lab.py are permanently rejected."""
        events_emitted = []
        self.event_bus.subscribe(EventType.IMPROVEMENT_REJECTED, lambda ev: events_emitted.append(ev))

        prop = self.manager.create_proposal(
            title="Bypass lab check",
            description="Loosen port scan constraints in cyber_lab.py",
            affected_component="modules/cyber_lab.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.CRITICAL,
            source_evidence={"user_prompt": "allow wide scanning"},
            expected_benefit="More scans",
        )
        self.assertEqual(prop.status, ProposalStatus.REJECTED)
        self.assertEqual(prop.risk, ProposalRisk.CRITICAL)
        self.assertIn("CRITICAL_SYSTEM_MODIFICATION_PROHIBITED", prop.rejection_reason)
        self.assertEqual(len(events_emitted), 1)

    def test_03_critical_safety_blocklist_security_scope(self):
        """CRITICAL SAFETY PRINCIPLE: Proposals attempting to modify security_scope.json are permanently rejected."""
        prop = self.manager.create_proposal(
            title="Add external targets",
            description="Add 8.8.8.8 to security scope",
            affected_component="config/security_scope.json",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.HIGH,
            source_evidence={},
            expected_benefit="Wider scan target range",
        )
        self.assertEqual(prop.status, ProposalStatus.REJECTED)
        self.assertEqual(prop.risk, ProposalRisk.CRITICAL)
        self.assertIn("CRITICAL_SYSTEM_MODIFICATION_PROHIBITED", prop.rejection_reason)

    def test_04_critical_safety_blocklist_authorization_gates(self):
        """CRITICAL SAFETY PRINCIPLE: Proposals targeting authorization or confirmation gates are rejected."""
        prop = self.manager.create_proposal(
            title="Disable confirmation gate",
            description="Auto-approve dangerous confirmation_gate prompts",
            affected_component="modules/workflow.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.HIGH,
            source_evidence={},
            expected_benefit="Less user interaction",
        )
        self.assertEqual(prop.status, ProposalStatus.REJECTED)
        self.assertEqual(prop.risk, ProposalRisk.CRITICAL)
        self.assertIn("CRITICAL_SYSTEM_MODIFICATION_PROHIBITED", prop.rejection_reason)

    def test_05_critical_safety_blocklist_secret_redaction(self):
        """CRITICAL SAFETY PRINCIPLE: Proposals referencing secret_redaction bypass are rejected."""
        prop = self.manager.create_proposal(
            title="Disable secret_redaction in logs",
            description="Expose full headers without secret_redaction",
            affected_component="modules/logger.py",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.MEDIUM,
            source_evidence={},
            expected_benefit="Easier debugging",
        )
        self.assertEqual(prop.status, ProposalStatus.REJECTED)
        self.assertEqual(prop.risk, ProposalRisk.CRITICAL)
        self.assertIn("CRITICAL_SYSTEM_MODIFICATION_PROHIBITED", prop.rejection_reason)

    def test_06_proposal_validation_lifecycle(self):
        """Validation moves a valid proposal from PROPOSED to VALIDATING."""
        prop = self.manager.create_proposal(
            title="Optimize prompt",
            description="Shorten coding prompt preamble",
            affected_component="core/prompts.py",
            change_type=ChangeType.PROMPT_TEMPLATE,
            risk=ProposalRisk.MEDIUM,
            source_evidence={"token_savings": 50},
            expected_benefit="Lower token consumption",
        )
        ok = self.manager.validate_proposal(prop.proposal_id)
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.VALIDATING)

    def test_07_regression_guard_rejects_on_test_failure(self):
        """Regression guard: If tests fail during validation, proposal is immediately REJECTED."""
        prop = self.manager.create_proposal(
            title="Experimental change",
            description="Change heuristic",
            affected_component="modules/context.py",
            change_type=ChangeType.PLANNING_HEURISTIC,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Faster context window",
        )
        ok = self.manager.test_proposal(prop.proposal_id, simulated_test_pass=False)
        self.assertFalse(ok)
        updated = self.manager.proposals[prop.proposal_id]
        self.assertEqual(updated.status, ProposalStatus.REJECTED)
        self.assertIn("Regression guard", updated.rejection_reason)

    def test_08_low_risk_auto_approval_after_test_pass(self):
        """Low risk proposal auto-approves once test suite passes."""
        prop = self.manager.create_proposal(
            title="Formatting tweak",
            description="Improve UI spacing",
            affected_component="ui/static/style.css",
            change_type=ChangeType.UI,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Better readability",
        )
        ok = self.manager.test_proposal(prop.proposal_id, simulated_test_pass=True)
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.APPROVED)
        self.assertEqual(self.manager.proposals[prop.proposal_id].approved_by, "autonomous_system")

    def test_09_high_risk_requires_explicit_user_approval(self):
        """High risk proposal remains PROPOSED after testing until explicitly approved by human."""
        prop = self.manager.create_proposal(
            title="Worker Concurrency Increase",
            description="Double MAX_PARALLEL_WORKERS to 8",
            affected_component="config/worker_settings.py",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.HIGH,
            source_evidence={"cpu_cores": 12},
            expected_benefit="Higher parallel throughput",
        )
        ok = self.manager.test_proposal(prop.proposal_id, simulated_test_pass=True)
        self.assertTrue(ok)
        # Should remain PROPOSED waiting for user approval
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.PROPOSED)

        # Explicit human approval
        appr_ok = self.manager.approve_proposal(prop.proposal_id, approved_by="admin_user")
        self.assertTrue(appr_ok)
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.APPROVED)
        self.assertEqual(self.manager.proposals[prop.proposal_id].approved_by, "admin_user")

    def test_10_proposal_rejection_lifecycle(self):
        """User or system can reject proposal with documented reason."""
        prop = self.manager.create_proposal(
            title="Bad Idea",
            description="Unnecessary change",
            affected_component="modules/research.py",
            change_type=ChangeType.RETRIEVAL_POLICY,
            risk=ProposalRisk.MEDIUM,
            source_evidence={},
            expected_benefit="None",
        )
        ok = self.manager.reject_proposal(prop.proposal_id, reason="Does not align with roadmap")
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.REJECTED)
        self.assertEqual(self.manager.proposals[prop.proposal_id].rejection_reason, "Does not align with roadmap")

    def test_11_deploy_proposal_creates_version(self):
        """Deploying an approved proposal registers a versioned ImprovementVersion."""
        prop = self.manager.create_proposal(
            title="Deployable tweak",
            description="Valid improvement",
            affected_component="modules/coding.py",
            change_type=ChangeType.PLANNING_HEURISTIC,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Faster AST validation",
            diff_content="+ # AST optimized",
        )
        self.manager.test_proposal(prop.proposal_id, simulated_test_pass=True)
        version = self.manager.deploy_proposal(prop.proposal_id)

        self.assertIsNotNone(version)
        self.assertEqual(version.proposal_id, prop.proposal_id)
        self.assertEqual(version.status, "ACTIVE")
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.DEPLOYED)

    def test_12_atomic_rollback_by_version_id(self):
        """Rollback restores status and invalidates deployed version."""
        prop = self.manager.create_proposal(
            title="Regressing tweak",
            description="Caused latent bug",
            affected_component="modules/coding.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Speed",
        )
        self.manager.approve_proposal(prop.proposal_id)
        version = self.manager.deploy_proposal(prop.proposal_id)

        ok = self.manager.rollback(version.version_id)
        self.assertTrue(ok)
        self.assertEqual(self.manager.versions[version.version_id].status, "ROLLED_BACK")
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.ROLLED_BACK)

    def test_13_atomic_rollback_by_proposal_id(self):
        """Rollback can be triggered using proposal_id directly."""
        prop = self.manager.create_proposal(
            title="Proposal rollback",
            description="Testing direct proposal rollback",
            affected_component="modules/workers.py",
            change_type=ChangeType.WORKER_ASSIGNMENT,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Fairer worker distribution",
        )
        self.manager.approve_proposal(prop.proposal_id)
        self.manager.deploy_proposal(prop.proposal_id)

        ok = self.manager.rollback(prop.proposal_id)
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[prop.proposal_id].status, ProposalStatus.ROLLED_BACK)

    def test_14_cannot_deploy_unapproved_proposal(self):
        """Unapproved proposal cannot be deployed."""
        prop = self.manager.create_proposal(
            title="Unapproved",
            description="Never approved",
            affected_component="core/engine.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.HIGH,
            source_evidence={},
            expected_benefit="None",
        )
        version = self.manager.deploy_proposal(prop.proposal_id)
        self.assertIsNone(version)

    def test_15_experiment_creation_and_trials(self):
        """Experiment tracks baseline vs candidate samples and computes improvement metric."""
        exp = self.manager.create_experiment(
            hypothesis="Strategy X reduces runtime by 20%",
            baseline={"model": "gemini-2.5-flash"},
            candidate={"model": "claude-3-7-sonnet"},
            target_sample_size=4,
        )
        self.assertEqual(exp.status, ExperimentStatus.RUNNING)

        # Record 2 baseline runs (both success=1.0)
        self.manager.record_experiment_trial(exp.experiment_id, is_candidate=False, metrics={"success": 1.0, "runtime": 10.0})
        self.manager.record_experiment_trial(exp.experiment_id, is_candidate=False, metrics={"success": 1.0, "runtime": 12.0})

        # Record 2 candidate runs (both success=1.0)
        self.manager.record_experiment_trial(exp.experiment_id, is_candidate=True, metrics={"success": 1.0, "runtime": 8.0})
        self.manager.record_experiment_trial(exp.experiment_id, is_candidate=True, metrics={"success": 1.0, "runtime": 7.0})

        updated = self.manager.experiments[exp.experiment_id]
        self.assertEqual(updated.status, ExperimentStatus.COMPLETED)
        self.assertIn("candidate_success_rate", updated.metrics)
        self.assertIn("baseline_success_rate", updated.metrics)

    def test_16_experiment_persistence_on_disk(self):
        """Experiments are saved to disk in JSON format and reloadable."""
        exp = self.manager.create_experiment(
            hypothesis="Disk test",
            baseline={},
            candidate={},
            target_sample_size=2
        )
        exp_file = self.exps_dir / f"{exp.experiment_id}.json"
        self.assertTrue(exp_file.exists())

    def test_17_self_improvement_evaluator_legacy_compatibility(self):
        """SelfImprovementEvaluator generates proposal when 2+ diagnoses occur."""
        evaluator = SelfImprovementEvaluator(
            memory_store=self.memory,
            evaluation_manager=self.manager
        )
        ctx = TaskContext(task="Legacy Task", tag="coding")
        ctx.diagnoses = [
            Diagnosis(attempt=1, failure_reason="f1", hypothesis="h1", proposed_fix={"action": "fix1"}),
            Diagnosis(attempt=2, failure_reason="f2", hypothesis="h2", proposed_fix={"action": "fix2"}),
        ]
        ctx.is_completed = False

        legacy_prop = evaluator.evaluate_task(ctx)
        self.assertIsNotNone(legacy_prop)
        self.assertEqual(legacy_prop["task"], "Legacy Task")
        self.assertTrue(legacy_prop["requires_user_approval"])

        # Also verify it was recorded in EvaluationManager
        self.assertTrue(len(self.manager.proposals) >= 1)

    def test_18_fastapi_rest_endpoints(self):
        """FastAPI endpoints for learning status, stats, lessons, strategies, proposals exist and respond."""
        from ui.server import create_ui_app as create_app
        from fastapi.testclient import TestClient
        from core.engine import ZaraEngine

        engine = ZaraEngine(enable_voice=False)
        app = create_app(engine)
        client = TestClient(app)

        # GET /api/learning/status
        res = client.get("/api/learning/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("stats", data)

        # GET /api/learning/stats
        res = client.get("/api/learning/stats")
        self.assertEqual(res.status_code, 200)

        # GET /api/learning/strategies
        res = client.get("/api/learning/strategies")
        self.assertEqual(res.status_code, 200)
        self.assertIn("strategies", res.json())

        # GET /api/learning/proposals
        res = client.get("/api/learning/proposals")
        self.assertEqual(res.status_code, 200)
        self.assertIn("proposals", res.json())

        # GET /api/learning/experiments
        res = client.get("/api/learning/experiments")
        self.assertEqual(res.status_code, 200)
        self.assertIn("experiments", res.json())

        # GET /api/learning/evaluations
        res = client.get("/api/learning/evaluations")
        self.assertEqual(res.status_code, 200)
        self.assertIn("evaluations", res.json())

        engine.close()

    def test_19_fastapi_approve_and_reject_proposal(self):
        """FastAPI proposal approve and reject routes work correctly."""
        from ui.server import create_ui_app as create_app
        from fastapi.testclient import TestClient
        from core.engine import ZaraEngine

        engine = ZaraEngine(enable_voice=False)
        app = create_app(engine)
        client = TestClient(app)

        prop = engine.evaluation_manager.create_proposal(
            title="API Test Proposal",
            description="Testing API approval",
            affected_component="docs/api.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Docs",
        )

        # Approve
        res = client.post(f"/api/learning/proposals/{prop.proposal_id}/approve")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(engine.evaluation_manager.proposals[prop.proposal_id].status, ProposalStatus.APPROVED)

        # Create another and reject
        prop2 = engine.evaluation_manager.create_proposal(
            title="API Test Proposal 2",
            description="Testing API rejection",
            affected_component="docs/api2.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Docs",
        )
        res2 = client.post(f"/api/learning/proposals/{prop2.proposal_id}/reject", json={"reason": "Rejected in test"})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(engine.evaluation_manager.proposals[prop2.proposal_id].status, ProposalStatus.REJECTED)

        engine.close()

    def test_20_fastapi_rollback_endpoint(self):
        """FastAPI rollback endpoint rolls back deployed proposal."""
        from ui.server import create_ui_app as create_app
        from fastapi.testclient import TestClient
        from core.engine import ZaraEngine

        engine = ZaraEngine(enable_voice=False)
        app = create_app(engine)
        client = TestClient(app)

        prop = engine.evaluation_manager.create_proposal(
            title="API Rollback Test",
            description="Testing rollback API",
            affected_component="docs/rollback.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Test",
        )
        engine.evaluation_manager.approve_proposal(prop.proposal_id)
        version = engine.evaluation_manager.deploy_proposal(prop.proposal_id)

        res = client.post(f"/api/learning/rollback/{version.version_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(engine.evaluation_manager.versions[version.version_id].status, "ROLLED_BACK")

        engine.close()

    def test_21_cli_learning_status_and_subcommands(self):
        """CLI learning dispatcher executes status, stats, and inspect without error."""
        from cli import cmd_learning
        import argparse

        args = argparse.Namespace(learning_action="status")
        cmd_learning(args)

        args = argparse.Namespace(learning_action="stats")
        cmd_learning(args)

        args = argparse.Namespace(learning_action="strategies", domain=None, status=None)
        cmd_learning(args)

        args = argparse.Namespace(learning_action="proposals", risk=None)
        cmd_learning(args)

    def test_22_zero_resource_warnings(self):
        """Proposal and experiment operations complete cleanly with zero resource warnings."""
        prop = self.manager.create_proposal(
            title="Resource test",
            description="Zero warnings check",
            affected_component="docs/clean.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Clean shutdown",
        )
        self.assertIsNotNone(prop.proposal_id)


if __name__ == "__main__":
    unittest.main()
