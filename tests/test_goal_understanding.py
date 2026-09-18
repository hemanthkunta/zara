"""Tests for ZARA Phase 11 - Goal Understanding, Ambiguity Detection & Requirements Extraction."""

import unittest
from modules.goals import (
    AmbiguityLevel,
    Assumption,
    Constraint,
    ConstraintType,
    Goal,
    GoalDomain,
    GoalParser,
    Requirement,
    RequirementType,
    SuccessCriterion,
)


class TestGoalUnderstanding(unittest.TestCase):
    """Test suite covering goal normalization, domain detection, requirements, assumptions, constraints, and ambiguity."""

    def test_01_goal_normalization(self):
        """GoalParser normalizes whitespace, conversational fluff, and punctuation."""
        raw = "   Please, can you implement a Python quicksort algorithm?   "
        normalized = GoalParser.normalize_request(raw)
        self.assertEqual(normalized, "implement a Python quicksort algorithm?")

        raw2 = "Zara,   create   a   blender forest scene. "
        normalized2 = GoalParser.normalize_request(raw2)
        self.assertEqual(normalized2, "create a blender forest scene.")

    def test_02_domain_detection_blender(self):
        """Blender domain is detected for 3D and rendering keywords."""
        goal = GoalParser.parse_goal("Create a realistic forest environment in Blender.")
        self.assertEqual(goal.domain, GoalDomain.BLENDER)
        self.assertTrue(any("terrain" in r.text.lower() or "blender" in r.text.lower() for r in goal.requirements))

    def test_03_domain_detection_cybersecurity(self):
        """Cybersecurity domain is detected for security and vulnerability keywords."""
        goal = GoalParser.parse_goal("Conduct a security assessment of my DVWA instance at http://127.0.0.1:8080/dvwa")
        self.assertEqual(goal.domain, GoalDomain.CYBERSECURITY)
        self.assertTrue(any(c.type == ConstraintType.AUTHORIZATION for c in goal.constraints))

    def test_04_domain_detection_coding_and_research(self):
        """Coding and research domains are detected appropriately."""
        coding_goal = GoalParser.parse_goal("Write code to implement a binary search tree with unit tests")
        self.assertEqual(coding_goal.domain, GoalDomain.CODING)

        research_goal = GoalParser.parse_goal("Research the latest advances in LLM reasoning and summarize papers")
        self.assertEqual(research_goal.domain, GoalDomain.RESEARCH)

    def test_05_ambiguity_detection_none_and_low(self):
        """Well-specified and moderate requests have NONE or LOW ambiguity without needing clarification."""
        goal = GoalParser.parse_goal("Implement a REST API endpoint for user authentication in auth.py with unit tests")
        self.assertEqual(goal.ambiguity_level, AmbiguityLevel.NONE)
        self.assertFalse(goal.clarification_needed)
        self.assertIsNone(goal.clarification_question)

        blender_goal = GoalParser.parse_goal("Create a blender forest")
        self.assertIn(blender_goal.ambiguity_level, (AmbiguityLevel.LOW, AmbiguityLevel.MEDIUM))
        self.assertFalse(blender_goal.clarification_needed)

    def test_06_ambiguity_detection_critical(self):
        """Extremely brief or vague goals trigger CRITICAL ambiguity and formulate clarification questions."""
        goal = GoalParser.parse_goal("deploy")
        self.assertEqual(goal.ambiguity_level, AmbiguityLevel.CRITICAL)
        self.assertTrue(goal.clarification_needed)
        self.assertIsNotNone(goal.clarification_question)
        self.assertIn("too brief", goal.clarification_question.lower())

    def test_07_ambiguity_detection_high_unauthorized_scope(self):
        """Cybersecurity goal with missing target triggers HIGH ambiguity clarification."""
        goal = GoalParser.parse_goal("Scan this server for open vulnerabilities")
        self.assertEqual(goal.ambiguity_level, AmbiguityLevel.HIGH)
        self.assertTrue(goal.clarification_needed)
        self.assertIn("target host", goal.clarification_question.lower())

    def test_08_requirement_extraction_categorization(self):
        """Requirements are separated into USER, TECHNICAL, and SAFETY types with safety precedence."""
        goal = GoalParser.parse_goal("Build a security assessment of my DVWA instance at http://127.0.0.1:8080/dvwa")
        req_types = {r.type for r in goal.requirements}
        self.assertIn(RequirementType.USER, req_types)
        self.assertIn(RequirementType.TECHNICAL, req_types)
        self.assertIn(RequirementType.SAFETY, req_types)

        # Safety requirement exists and is mandatory
        safety_reqs = [r for r in goal.requirements if r.type == RequirementType.SAFETY]
        self.assertTrue(len(safety_reqs) > 0)
        self.assertTrue(all(r.mandatory for r in safety_reqs))

    def test_09_assumption_registry(self):
        """Assumptions are explicitly tracked with confidence, source, and verification status."""
        goal = GoalParser.parse_goal("Render a 3D Suzanne monkey head in Blender")
        self.assertTrue(len(goal.assumptions) > 0)
        asm = goal.assumptions[0]
        self.assertIn("Blender", asm.statement)
        self.assertEqual(asm.status, "PENDING")
        self.assertFalse(asm.verified)

        # Verify serialization and deserialization
        asm_dict = asm.to_dict()
        restored = Assumption.from_dict(asm_dict)
        self.assertEqual(restored.statement, asm.statement)
        self.assertEqual(restored.confidence, asm.confidence)

    def test_10_constraint_system(self):
        """Constraints are modeled explicitly with type, value, and enforcement."""
        goal = GoalParser.parse_goal("Run test suite on our python repository with 3 retries max")
        cst_types = {c.type for c in goal.constraints}
        self.assertIn(ConstraintType.BUDGET, cst_types)
        self.assertTrue(all(c.enforced for c in goal.constraints))

        c = Constraint(id="c1", type=ConstraintType.SAFETY, value="no_rm_rf", source="safety_policy")
        c_dict = c.to_dict()
        restored_c = Constraint.from_dict(c_dict)
        self.assertEqual(restored_c.type, ConstraintType.SAFETY)
        self.assertEqual(restored_c.value, "no_rm_rf")

    def test_11_success_criteria(self):
        """Explicit completion criteria are defined with verification methods and required flags."""
        goal = GoalParser.parse_goal("Create unit tests for the data parser module")
        self.assertTrue(len(goal.success_criteria) > 0)
        crit = goal.success_criteria[0]
        self.assertTrue(crit.required)
        self.assertEqual(crit.status, "PENDING")

        crit_dict = crit.to_dict()
        restored_crit = SuccessCriterion.from_dict(crit_dict)
        self.assertEqual(restored_crit.verification_method, crit.verification_method)

    def test_12_goal_serialization_roundtrip(self):
        """Goal objects accurately serialize to and from dictionary manifests."""
        goal = GoalParser.parse_goal("Generate a procedural forest scene in Blender and render output")
        goal_dict = goal.to_dict()
        restored = Goal.from_dict(goal_dict)

        self.assertEqual(restored.goal_id, goal.goal_id)
        self.assertEqual(restored.domain, GoalDomain.BLENDER)
        self.assertEqual(len(restored.requirements), len(goal.requirements))
        self.assertEqual(len(restored.constraints), len(goal.constraints))
        self.assertEqual(len(restored.assumptions), len(goal.assumptions))
        self.assertEqual(len(restored.success_criteria), len(goal.success_criteria))


if __name__ == "__main__":
    unittest.main()
