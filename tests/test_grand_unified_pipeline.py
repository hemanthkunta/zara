"""
Grand Unified Pipeline Test for ZARA Autonomous Agent.
Validates the complete 10-tier autonomous interaction loop:
🎤 VOICE -> 🧠 INTENT -> 📋 MASTER PLAN -> 🌐 RESEARCH -> 💻 CODING
-> 🖥️ MAC CONTROL -> 👁️ VISION -> 🐛 DEBUG -> 🧠 MEMORY -> 🔊 VOICE RESPONSE
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.engine import ZaraEngine
from core.state import (
    VoiceState,
    VoiceCommandType,
    PlanStep,
    StepStatus,
    ActionType,
    ExecutionResult,
    GUIState,
    GUIElement
)
from modules.voice import (
    MockSTTProvider,
    MockTTSProvider,
    MockVADProvider,
    detect_wake_word,
    classify_voice_input,
    summarize_for_voice
)
from modules.voice_controller import VoiceInteractionController
from modules.vision import MockVisionProvider
from modules.memory import MemoryStore


class TestGrandUnifiedPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="zara_unified_test_")
        self.workspace = Path(self.tmp_dir) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.db_path = self.workspace / "test_memory.db"

        self.engine = ZaraEngine(
            workspace_root=str(self.workspace),
            enable_voice=False
        )

        self.mock_stt = MockSTTProvider()
        self.mock_tts = MockTTSProvider()
        self.mock_vad = MockVADProvider()

        self.controller = VoiceInteractionController(
            engine=self.engine,
            stt_provider=self.mock_stt,
            tts_provider=self.mock_tts,
            vad_provider=self.mock_vad,
            wake_word="ZARA"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_complete_10_tier_unified_pipeline(self):
        """
        Execute and verify the full 10-stage autonomous loop end-to-end.
        """
        # =================================================================
        # TIER 1: 🎤 VOICE INPUT
        # =================================================================
        spoken_utterance = "ZARA, research python math algorithms, write a calculator module, inspect the screen, verify tests, and report."
        self.mock_stt.set_transcription(spoken_utterance, confidence=0.98)
        stt_result = self.mock_stt.transcribe(b"raw_audio_chunk")
        self.assertTrue(stt_result.success)
        self.assertIn("ZARA", stt_result.text)

        # =================================================================
        # TIER 2: 🧠 INTENT & WAKE WORD
        # =================================================================
        is_wake, clean_command = detect_wake_word(stt_result.text, wake_word="ZARA")
        self.assertTrue(is_wake)
        classification = classify_voice_input(clean_command)
        self.assertEqual(classification.command_type, VoiceCommandType.COMMAND)
        self.assertIn("research", classification.clean_text)

        # =================================================================
        # TIER 3: 📋 MASTER PLAN
        # =================================================================
        context = self.engine.perceive(classification.clean_text, tag="unified_pipeline")
        self.assertIsNotNone(context)

        # Define multi-step plan representing the workflow
        step_research = PlanStep(
            id=1,
            title="Research Math Algorithms",
            action_type=ActionType.SEARCH,
            description="Search for math algorithms",
            target="python math algorithms",
            tool="web_search",
            arguments={"query": "python math gcd algorithms", "num_results": 3},
            success_condition="Search results contain authoritative documentation"
        )
        step_code = PlanStep(
            id=2,
            title="Write Math Module",
            action_type=ActionType.CODE,
            description="Write math_utils.py",
            target="math_utils.py",
            tool="write_file",
            arguments={
                "path": "math_utils.py",
                "content": "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n"
            },
            dependencies=[1],
            success_condition="math_utils.py created on disk"
        )
        step_test_code = PlanStep(
            id=3,
            title="Write Math Unit Tests",
            action_type=ActionType.CODE,
            description="Write test_math_utils.py",
            target="test_math_utils.py",
            tool="write_file",
            arguments={
                "path": "test_math_utils.py",
                "content": "import unittest\nfrom math_utils import add, multiply\n\nclass TestMath(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n    def test_multiply(self):\n        self.assertEqual(multiply(4, 5), 20)\n\nif __name__ == '__main__':\n    unittest.main()\n"
            },
            dependencies=[2],
            success_condition="test_math_utils.py created on disk"
        )
        context.plan = [step_research, step_code, step_test_code]
        self.assertEqual(len(context.plan), 3)

        # =================================================================
        # TIER 4: 🌐 RESEARCH
        # =================================================================
        search_res = self.engine.tools.execute("web_search", {"query": "python math algorithms", "max_results": 2})
        self.assertTrue(search_res.success)
        self.assertIn("results", search_res.data)
        # Record research source in context
        context.add_source(
            source_id="src_math_docs",
            url="https://docs.python.org/3/library/math.html",
            title="Python Math Documentation",
            domain="python.org",
            is_authoritative=True
        )
        self.assertEqual(len(context.sources), 1)

        # =================================================================
        # TIER 5: 💻 CODING
        # =================================================================
        code_res = self.engine.tools.execute("write_file", step_code.arguments)
        self.assertTrue(code_res.success)
        self.assertTrue((self.workspace / "math_utils.py").exists())

        test_write_res = self.engine.tools.execute("write_file", step_test_code.arguments)
        self.assertTrue(test_write_res.success)
        self.assertTrue((self.workspace / "test_math_utils.py").exists())

        # Static syntax validation
        valid_syntax, syntax_err = self.engine.coding.validate_static("math_utils.py")
        self.assertTrue(valid_syntax)
        self.assertIsNone(syntax_err)

        # =================================================================
        # TIER 6: 🖥️ MAC CONTROL
        # =================================================================
        # Test mouse movement validation
        move_res = self.engine.tools.execute("mouse_move", {"x": 500, "y": 400})
        self.assertTrue(move_res.success)

        # Verify active window detection
        window_res = self.engine.tools.execute("get_active_window", {})
        self.assertIsNotNone(window_res)

        # =================================================================
        # TIER 7: 👁️ VISION
        # =================================================================
        mock_vision = MockVisionProvider(
            predefined_elements=[
                {"type": "window", "label": "IDE Terminal", "x": 0, "y": 0, "width": 1200, "height": 800},
                {"type": "button", "label": "Run Tests", "x": 100, "y": 50, "width": 80, "height": 30}
            ],
            simulated_app="Visual Studio Code",
            simulated_title="math_utils.py - ZARA Workspace"
        )
        self.engine.vision.set_provider(mock_vision)
        gui_state = self.engine.vision.parse_gui_state("dummy_screenshot.png")
        self.assertEqual(gui_state.application, "Visual Studio Code")
        self.assertEqual(len(gui_state.elements), 2)
        run_btn = gui_state.find_element("Run Tests", "button")
        self.assertIsNotNone(run_btn)
        self.assertEqual(run_btn.center_x, 140)

        # =================================================================
        # TIER 8: 🐛 DEBUG & TEST EXECUTION
        # =================================================================
        test_exec_res = self.engine.tools.execute(
            "terminal_execute",
            {"command": "python3 -m unittest test_math_utils.py"}
        )
        self.assertTrue(test_exec_res.success)
        self.assertEqual(test_exec_res.data["exit_code"], 0)
        output = test_exec_res.data.get("stdout", "") + test_exec_res.data.get("stderr", "")
        self.assertIn("OK", output)

        # Debug diagnosis verification
        diag = self.engine.debugging.diagnose_failure(
            step_title="Unit Tests",
            expected_condition="Tests exit with 0",
            error_output=output
        )
        self.assertIsNotNone(diag.hypothesis)

        # =================================================================
        # TIER 9: 🧠 MEMORY & REFLECTION
        # =================================================================
        reflection = self.engine.reflect(context)
        self.assertIsNotNone(reflection.lesson)
        self.engine.persist(reflection)

        # Verify lessons retrievable from memory
        lessons = self.engine.memory.search_lessons("math algorithms", limit=1)
        self.assertGreaterEqual(len(lessons), 1)

        # =================================================================
        # TIER 10: 🔊 VOICE RESPONSE
        # =================================================================
        raw_final_report = (
            f"Successfully executed all tasks for '{clean_command}'. "
            f"Created math_utils.py with add() and multiply(). "
            f"All unit tests passed. Screen verified in Visual Studio Code. "
            f"Lessons persisted to long-term memory."
        )
        spoken_summary = summarize_for_voice(raw_final_report, max_length=150)
        self.assertLessEqual(len(spoken_summary), 250)

        tts_res = self.mock_tts.synthesize(spoken_summary)
        self.assertTrue(tts_res.success)
        self.mock_tts.speak(spoken_summary)
        self.assertTrue(self.mock_tts.is_speaking_state)
        self.assertIn(spoken_summary, self.mock_tts.synthesized_utterances)

        # Final verification: verify zero leaks and clean state
        self.assertEqual(len(context.sources), 1)
        self.assertTrue((self.workspace / "math_utils.py").exists())


if __name__ == "__main__":
    unittest.main()
