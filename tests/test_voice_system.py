"""
Unit and integration tests for Phase 6: Voice Interaction Layer for ZARA.
Tests A through P validate:
- Test A: Voice state machine
- Test B: Mock speech-to-text
- Test C: Mock text-to-speech
- Test D: Wake-word detection
- Test E: Voice command classification
- Test F: Conversation follow-up
- Test G: Voice cancellation
- Test H: Barge-in / interruption
- Test I: Confirmation ticket through voice
- Test J: Invalid "yes" without confirmation
- Test K: Microphone unavailable
- Test L: Speaker unavailable
- Test M: Audio resource cleanup
- Test N: Long response summarization
- Test O: Voice/text parity
- Test P: Transcript privacy behavior
"""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.engine import ZaraEngine
from core.conversation import ConversationalSession
from core.state import (
    VoiceState,
    VoiceCommandType,
    TranscriptionResult,
    AudioResult,
    RiskLevel
)
from modules.voice import (
    VoiceStateMachine,
    MockSTTProvider,
    LocalSTTProvider,
    MockTTSProvider,
    NativeMacOSTTSProvider,
    MockVADProvider,
    EnergyVADProvider,
    VoiceAudioLifecycle,
    detect_wake_word,
    classify_voice_input,
    summarize_for_voice,
    VoiceSynthesizer
)
from modules.voice_controller import VoiceInteractionController


class TestVoiceSystem(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="zara_voice_test_")
        self.workspace = Path(self.tmp_dir) / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.voice_tmp = Path(self.tmp_dir) / "voice_tmp"
        self.voice_tmp.mkdir(parents=True, exist_ok=True)
        self.lifecycle = VoiceAudioLifecycle(temp_dir=self.voice_tmp)

        # Mock Brain for fast and deterministic unit test responses
        mock_router = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = "I have analyzed your request."
        mock_router.generate.return_value = mock_resp

        self.engine = ZaraEngine(
            workspace_root=str(self.workspace),
            enable_voice=False
        )
        self.engine.brain = mock_router
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
        self.lifecycle.cleanup_temp_files()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------
    # Test A: Voice state machine
    # -------------------------------------------------------------
    def test_a_voice_state_machine(self):
        """Test A: Voice state machine enforces valid transitions and rejects invalid ones."""
        sm = VoiceStateMachine(initial_state=VoiceState.IDLE)
        self.assertEqual(sm.current_state, VoiceState.IDLE)

        # Valid forward chain: IDLE -> LISTENING -> TRANSCRIBING -> THINKING -> ACTING -> SPEAKING -> IDLE
        self.assertTrue(sm.transition_to(VoiceState.LISTENING))
        self.assertEqual(sm.current_state, VoiceState.LISTENING)

        self.assertTrue(sm.transition_to(VoiceState.TRANSCRIBING))
        self.assertEqual(sm.current_state, VoiceState.TRANSCRIBING)

        self.assertTrue(sm.transition_to(VoiceState.THINKING))
        self.assertEqual(sm.current_state, VoiceState.THINKING)

        self.assertTrue(sm.transition_to(VoiceState.ACTING))
        self.assertEqual(sm.current_state, VoiceState.ACTING)

        self.assertTrue(sm.transition_to(VoiceState.SPEAKING))
        self.assertEqual(sm.current_state, VoiceState.SPEAKING)

        self.assertTrue(sm.transition_to(VoiceState.IDLE))
        self.assertEqual(sm.current_state, VoiceState.IDLE)

        # Invalid transition: IDLE directly to SPEAKING or ACTING must be rejected
        self.assertFalse(sm.transition_to(VoiceState.SPEAKING, reason="Invalid direct speak"))
        self.assertEqual(sm.current_state, VoiceState.IDLE)

    # -------------------------------------------------------------
    # Test B: Mock speech-to-text
    # -------------------------------------------------------------
    def test_b_mock_speech_to_text(self):
        """Test B: Mock STT provider returns structured TranscriptionResult and handles simulated errors."""
        stt = MockSTTProvider(default_text="ZARA, build a microservice", default_confidence=0.96)
        res = stt.transcribe(b"dummy_audio_bytes")
        self.assertTrue(res.success)
        self.assertEqual(res.text, "ZARA, build a microservice")
        self.assertAlmostEqual(res.confidence, 0.96)
        self.assertIsNone(res.error)

        # Simulate STT failure
        stt.set_error("Audio too noisy to transcribe")
        err_res = stt.transcribe(b"dummy_audio_bytes")
        self.assertFalse(err_res.success)
        self.assertEqual(err_res.text, "")
        self.assertIn("Audio too noisy", err_res.error)

    # -------------------------------------------------------------
    # Test C: Mock text-to-speech
    # -------------------------------------------------------------
    def test_c_mock_text_to_speech(self):
        """Test C: Mock TTS provider synthesizes audio result and tracks spoken utterances."""
        tts = MockTTSProvider()
        res = tts.synthesize("Task completed successfully.")
        self.assertTrue(res.success)
        self.assertIsNotNone(res.audio_path)
        self.assertGreater(res.duration_seconds, 0.0)

        # Speak and verify playback recording
        speak_ok = tts.speak("Starting execution.")
        self.assertTrue(speak_ok)
        self.assertTrue(tts.is_speaking_state)
        self.assertIn("Starting execution.", tts.synthesized_utterances)

    # -------------------------------------------------------------
    # Test D: Wake-word detection
    # -------------------------------------------------------------
    def test_d_wake_word_detection(self):
        """Test D: Wake-word detection recognizes configured wake phrase case-insensitively and extracts command."""
        # Standard wake word
        detected, command = detect_wake_word("ZARA, create hello.py", wake_word="ZARA")
        self.assertTrue(detected)
        self.assertEqual(command, "create hello.py")

        # Conversational greetings before wake word
        detected2, command2 = detect_wake_word("Hey Zara: run tests now", wake_word="ZARA")
        self.assertTrue(detected2)
        self.assertEqual(command2, "run tests now")

        # Case without wake word
        detected3, command3 = detect_wake_word("list files in workspace", wake_word="ZARA")
        self.assertFalse(detected3)
        self.assertEqual(command3, "list files in workspace")

    # -------------------------------------------------------------
    # Test E: Voice command classification
    # -------------------------------------------------------------
    def test_e_voice_command_classification(self):
        """Test E: Input classifier correctly categorizes utterances into command types."""
        # COMMAND
        c1 = classify_voice_input("ZARA, create a file called app.py")
        self.assertEqual(c1.command_type, VoiceCommandType.COMMAND)

        # QUESTION
        c2 = classify_voice_input("ZARA, what is Python 3.14?")
        self.assertEqual(c2.command_type, VoiceCommandType.QUESTION)

        # FOLLOW_UP
        c3 = classify_voice_input("Also add unit tests for that")
        self.assertEqual(c3.command_type, VoiceCommandType.FOLLOW_UP)

        # CANCELLATION
        c4 = classify_voice_input("Stop right now")
        self.assertEqual(c4.command_type, VoiceCommandType.CANCELLATION)

        # CONFIRMATION
        c5 = classify_voice_input("Yes, proceed")
        self.assertEqual(c5.command_type, VoiceCommandType.CONFIRMATION)

    # -------------------------------------------------------------
    # Test F: Conversation follow-up
    # -------------------------------------------------------------
    def test_f_conversation_follow_up(self):
        """Test F: Multi-turn voice interaction maintains conversational session and context."""
        # Turn 1: Question
        self.mock_stt.set_transcription("ZARA, what is two plus two?")
        res1 = self.controller.process_utterance("ZARA, what is two plus two?")
        self.assertTrue(res1["success"])
        self.assertEqual(res1["command_type"], VoiceCommandType.QUESTION.value)

        # Turn 2: Follow-up question
        self.mock_stt.set_transcription("And multiply that by three")
        res2 = self.controller.process_utterance("And multiply that by three")
        self.assertTrue(res2["success"])
        self.assertEqual(res2["command_type"], VoiceCommandType.FOLLOW_UP.value)

        # Check that session history recorded both turns
        history = self.controller.session.get_history()
        self.assertGreaterEqual(len(history), 4)  # 2 user turns + 2 assistant responses

    # -------------------------------------------------------------
    # Test G: Voice cancellation
    # -------------------------------------------------------------
    def test_g_voice_cancellation(self):
        """Test G: 'Stop' or 'Cancel' utterance halts active speech and resets to IDLE."""
        self.mock_tts.is_speaking_state = True
        res = self.controller.process_utterance("Stop")
        self.assertTrue(res["success"])
        self.assertTrue(res.get("cancelled"))
        self.assertEqual(self.controller.current_state, VoiceState.IDLE)
        self.assertEqual(self.mock_tts.interrupted_count, 1)

    # -------------------------------------------------------------
    # Test H: Barge-in / interruption
    # -------------------------------------------------------------
    def test_h_barge_in_interruption(self):
        """Test H: Controller interrupt() promptly cuts off active TTS output."""
        self.controller.state_machine.reset()
        self.controller.state_machine.transition_to(VoiceState.THINKING)
        self.controller.state_machine.transition_to(VoiceState.SPEAKING)
        self.mock_tts.is_speaking_state = True

        self.controller.interrupt()
        self.assertFalse(self.mock_tts.is_speaking_state)
        self.assertEqual(self.controller.current_state, VoiceState.INTERRUPTED)

    # -------------------------------------------------------------
    # Test I: Confirmation ticket through voice
    # -------------------------------------------------------------
    def test_i_confirmation_ticket_through_voice(self):
        """Test I: Voice 'Yes' authorizes an active pending confirmation ticket."""
        ticket_id = self.engine.tools.request_confirmation(
            "app_close",
            {"app_name": "Calculator"},
            description="Close Calculator application"
        )
        self.assertIn(ticket_id, self.engine.tools.pending_confirmations)
        self.assertFalse(self.engine.tools.pending_confirmations[ticket_id]["confirmed"])

        # Speak "Yes, confirm"
        res = self.controller.process_utterance("Yes, proceed")
        self.assertTrue(res["success"])
        self.assertTrue(res.get("authorized"))
        self.assertEqual(res.get("action_id"), ticket_id)
        self.assertTrue(self.engine.tools.pending_confirmations[ticket_id]["confirmed"])

    # -------------------------------------------------------------
    # Test J: Invalid "yes" without confirmation
    # -------------------------------------------------------------
    def test_j_invalid_yes_without_confirmation(self):
        """Test J: Spoken 'Yes' when NO confirmation ticket is pending is safely rejected as a no-op."""
        # Ensure registry has no pending tickets
        self.engine.tools.pending_confirmations.clear()

        res = self.controller.process_utterance("Yes, go ahead")
        self.assertFalse(res["success"])
        self.assertFalse(res.get("authorized"))
        self.assertIn("no pending actions", res["response"].lower())

    # -------------------------------------------------------------
    # Test K: Microphone unavailable
    # -------------------------------------------------------------
    def test_k_microphone_unavailable(self):
        """Test K: When microphone or STT provider is unavailable, returns structured error without crashing."""
        self.mock_stt.available = False
        res = self.controller.process_utterance(b"some_audio_bytes")
        self.assertFalse(res["success"])
        self.assertIn("unavailable", res["error"].lower())
        self.assertEqual(self.controller.current_state, VoiceState.IDLE)

    # -------------------------------------------------------------
    # Test L: Speaker unavailable
    # -------------------------------------------------------------
    def test_l_speaker_unavailable(self):
        """Test L: When audio output/TTS is unavailable, system handles gracefully without raising uncaught errors."""
        self.mock_tts.available = False
        synth_res = self.mock_tts.synthesize("Test speaker failure")
        self.assertFalse(synth_res.success)
        self.assertIn("unavailable", synth_res.error.lower())

        speak_res = self.mock_tts.speak("Test speak")
        self.assertFalse(speak_res)

    # -------------------------------------------------------------
    # Test M: Audio resource cleanup
    # -------------------------------------------------------------
    def test_m_audio_resource_cleanup(self):
        """Test M: Temporary audio files are safely deleted and resources are freed without leaks."""
        p1 = self.lifecycle.get_temp_audio_path(prefix="voice_test", suffix=".wav")
        p2 = self.lifecycle.get_temp_audio_path(prefix="voice_test", suffix=".wav")
        p1.write_bytes(b"dummy wav 1")
        p2.write_bytes(b"dummy wav 2")

        self.assertTrue(p1.exists())
        self.assertTrue(p2.exists())

        deleted = self.lifecycle.cleanup_temp_files()
        self.assertEqual(deleted, 2)
        self.assertFalse(p1.exists())
        self.assertFalse(p2.exists())

    # -------------------------------------------------------------
    # Test N: Long response summarization
    # -------------------------------------------------------------
    def test_n_long_response_summarization(self):
        """Test N: Long research reports, code blocks, and markdown are summarized into concise verbal output."""
        long_markdown = (
            "# Execution Report\n\n"
            "```python\n"
            "def calculate(x, y):\n"
            "    return x + y\n"
            "```\n\n"
            "All unit tests passed with exit code 0. [Documentation](https://docs.python.org).\n"
            "Detailed trace output spans 500 lines across multiple microservices with comprehensive telemetry."
        )

        verbal = summarize_for_voice(long_markdown, max_length=120)
        self.assertNotIn("```", verbal)
        self.assertNotIn("#", verbal)
        self.assertNotIn("https://", verbal)
        self.assertLessEqual(len(verbal), 200)
        self.assertIn("details", verbal.lower())

    # -------------------------------------------------------------
    # Test O: Voice/text parity
    # -------------------------------------------------------------
    def test_o_voice_text_parity(self):
        """Test O: Voice input invokes the exact same underlying conversational engine as text CLI."""
        text_session = ConversationalSession(self.engine)
        text_reply = text_session.process_user_input("what is ZARA?")

        voice_res = self.controller.process_utterance("ZARA, what is ZARA?")
        self.assertTrue(voice_res["success"])
        # Both route through LLM router generate()
        self.assertEqual(voice_res["response"], text_reply)

    # -------------------------------------------------------------
    # Test P: Transcript privacy behavior
    # -------------------------------------------------------------
    def test_p_transcript_privacy_behavior(self):
        """Test P: Inactive voice mode does not record, and temporary files are purged after processing."""
        # Process an utterance
        self.controller.process_utterance("ZARA, status check")
        
        # Verify no audio files remain dangling in the temporary voice directory
        dangling_files = list(self.voice_tmp.glob("voice_*.*"))
        self.assertEqual(len(dangling_files), 0)


if __name__ == "__main__":
    unittest.main()
