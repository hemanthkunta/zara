"""
ZARA Voice Interaction Controller: Orchestrates the bidirectional voice interaction loop.
Coordinates VAD, STT, input classification, conversation context, agent execution,
action confirmation tickets, verbal response summarization, TTS playback, and barge-in.
"""
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Union

from config.settings import (
    WAKE_WORD,
    MAX_RECORDING_SECONDS,
    VOICE_SILENCE_TIMEOUT,
    TTS_ENABLED,
    MAX_VOICE_SUMMARY_LENGTH
)
from core.state import (
    VoiceState,
    VoiceCommandType,
    VoiceClassificationResult,
    TranscriptionResult,
    AudioResult,
    PendingConfirmation,
    TaskContext
)
from core.observability import audit_logger
from core.conversation import ConversationalSession
from modules.voice import (
    SpeechToTextProvider,
    TextToSpeechProvider,
    VoiceActivityDetector,
    MockSTTProvider,
    LocalSTTProvider,
    MockTTSProvider,
    NativeMacOSTTSProvider,
    MockVADProvider,
    EnergyVADProvider,
    VoiceStateMachine,
    detect_wake_word,
    classify_voice_input,
    summarize_for_voice,
    voice_lifecycle
)


class VoiceInteractionController:
    """
    Main Voice Interaction Controller providing parity with ZARA's CLI and conversational text engine.
    """

    def __init__(
        self,
        engine: Any,
        stt_provider: Optional[SpeechToTextProvider] = None,
        tts_provider: Optional[TextToSpeechProvider] = None,
        vad_provider: Optional[VoiceActivityDetector] = None,
        wake_word: str = WAKE_WORD,
        session: Optional[ConversationalSession] = None,
        require_wake_word: bool = False
    ):
        self.engine = engine
        self.stt_provider = stt_provider or MockSTTProvider()
        self.tts_provider = tts_provider or NativeMacOSTTSProvider()
        self.vad_provider = vad_provider or MockVADProvider()
        self.wake_word = wake_word
        self.require_wake_word = require_wake_word
        self.session = session or ConversationalSession(self.engine)
        self.state_machine = VoiceStateMachine(initial_state=VoiceState.IDLE)
        self.last_transcript: Optional[str] = None
        self.last_response: Optional[str] = None
        self.active_context: Dict[str, Any] = self.session.active_context

    @property
    def current_state(self) -> VoiceState:
        return self.state_machine.current_state

    def process_utterance(self, audio_or_text: Union[str, bytes], **kwargs) -> Dict[str, Any]:
        """
        Process a single spoken utterance through the full voice pipeline:
        VAD -> STT -> Wake Detection -> Intent Classification -> Confirmation Gate -> Agent Loop -> TTS.
        """
        audit_logger.log_event("VOICE_SESSION_START", action="process_utterance")
        
        # 1. State: LISTENING
        if not self.state_machine.transition_to(VoiceState.LISTENING, reason="User utterance received"):
            # If speaking or interrupted, reset to IDLE first
            self.state_machine.reset()
            self.state_machine.transition_to(VoiceState.LISTENING, reason="Reset and listen")

        # 2. State: TRANSCRIBING
        self.state_machine.transition_to(VoiceState.TRANSCRIBING, reason="Transcribing audio input")
        transcription = self._transcribe_input(audio_or_text)
        if not transcription.success:
            self.state_machine.transition_to(VoiceState.ERROR, reason=transcription.error or "STT failed")
            err_msg = transcription.error or "Sorry, I could not understand the audio."
            self._speak_verbal_reply(err_msg)
            self.state_machine.transition_to(VoiceState.IDLE, reason="Recovered to idle")
            return {
                "success": False,
                "error": err_msg,
                "text": "",
                "response": err_msg,
                "state": self.state_machine.current_state.value
            }

        raw_text = transcription.text.strip()
        self.last_transcript = raw_text

        # 3. Wake-word detection & check
        is_wake, clean_command = detect_wake_word(raw_text, self.wake_word)
        if is_wake:
            audit_logger.log_event("WAKE_WORD_DETECTED", action="wake", extra={"wake_word": self.wake_word})

        if self.require_wake_word and not is_wake:
            # Drop utterance if wake word required and not found
            self.state_machine.transition_to(VoiceState.IDLE, reason="Wake word not detected")
            return {
                "success": True,
                "ignored": True,
                "reason": "Wake word not detected",
                "text": raw_text,
                "state": self.state_machine.current_state.value
            }

        # 4. Classify Voice Command
        classification = classify_voice_input(clean_command or raw_text)
        audit_logger.log_event(
            "VOICE_INPUT_CLASSIFIED",
            action="classify",
            extra={"command_type": classification.command_type.value, "clean_text": classification.clean_text}
        )

        # 5. Handle CANCELLATION / BARGE-IN
        if classification.command_type == VoiceCommandType.CANCELLATION:
            self.tts_provider.interrupt()
            self.state_machine.transition_to(VoiceState.INTERRUPTED, reason="User commanded stop/cancel")
            reply = "Action cancelled and speech stopped."
            self.state_machine.transition_to(VoiceState.IDLE, reason="Reset after cancel")
            return {
                "success": True,
                "cancelled": True,
                "response": reply,
                "command_type": classification.command_type.value,
                "state": self.state_machine.current_state.value
            }

        # 6. Handle CONFIRMATION GATE
        if classification.command_type == VoiceCommandType.CONFIRMATION:
            res = self._handle_voice_confirmation(classification.clean_text)
            self._speak_verbal_reply(res["response"])
            self.state_machine.transition_to(VoiceState.IDLE, reason="Confirmation processed")
            return res

        # 7. State: THINKING
        self.state_machine.transition_to(VoiceState.THINKING, reason="Planning or answering query")

        # 8. Route into Agent Engine / Conversational Session
        if classification.command_type in (VoiceCommandType.COMMAND, VoiceCommandType.ACTING if hasattr(VoiceCommandType, "ACTING") else None):
            self.state_machine.transition_to(VoiceState.ACTING, reason="Executing tool plan")

        # Process input via ConversationalSession
        agent_reply = self.session.process_user_input(classification.clean_text or raw_text)
        self.last_response = agent_reply

        # 9. State: SPEAKING
        self.state_machine.transition_to(VoiceState.SPEAKING, reason="Speaking response")
        verbal_summary = summarize_for_voice(agent_reply, max_length=MAX_VOICE_SUMMARY_LENGTH)
        self.tts_provider.speak(verbal_summary, async_mode=False)

        # 10. Clean up audio resources & return to IDLE
        voice_lifecycle.cleanup_temp_files()
        self.state_machine.transition_to(VoiceState.IDLE, reason="Turn complete")

        audit_logger.log_event("VOICE_SESSION_COMPLETE", action="complete")

        return {
            "success": True,
            "text": raw_text,
            "command": classification.clean_text,
            "command_type": classification.command_type.value,
            "response": agent_reply,
            "verbal_summary": verbal_summary,
            "state": self.state_machine.current_state.value
        }

    def interrupt(self) -> None:
        """Trigger immediate barge-in interruption of active voice output."""
        self.tts_provider.interrupt()
        if self.state_machine.current_state == VoiceState.SPEAKING:
            self.state_machine.transition_to(VoiceState.INTERRUPTED, reason="External interruption signal")
        audit_logger.log_event("VOICE_INTERRUPTED", action="interrupt")

    def _transcribe_input(self, audio_or_text: Union[str, bytes]) -> TranscriptionResult:
        """Helper to transcribe input using configured STT provider."""
        if isinstance(audio_or_text, str) and not Path(audio_or_text).exists():
            # Already transcribed text
            return TranscriptionResult(
                success=True,
                text=audio_or_text,
                confidence=1.0,
                duration_seconds=0.1
            )
        return self.stt_provider.transcribe(audio_or_text)

    def _handle_voice_confirmation(self, text: str) -> Dict[str, Any]:
        """
        Verify if an active confirmation ticket exists.
        Authorizes ONLY if a valid pending confirmation ticket is present.
        """
        text_lower = text.lower().strip()
        first_token = re.split(r"[,:\s]+", text_lower)[0] if text_lower else ""
        positive_phrases = ["yes", "confirm", "proceed", "go ahead", "do it", "sure", "affirmative", "authorize", "authorized"]
        is_positive = text_lower in positive_phrases or first_token in positive_phrases or any(text_lower.startswith(p) for p in positive_phrases)
        
        # Check engine tool registry for pending tickets
        pending = getattr(self.engine.tools, "pending_confirmations", {})
        active_tickets = [t for t in pending.values() if not t.get("confirmed", False)]

        if not active_tickets:
            reply = "There are no pending actions requiring confirmation."
            audit_logger.log_event("VOICE_CONFIRMATION_REJECTED", action="no_pending_ticket", extra={"utterance": text})
            return {
                "success": False,
                "authorized": False,
                "response": reply,
                "command_type": VoiceCommandType.CONFIRMATION.value,
                "state": self.state_machine.current_state.value
            }

        ticket = active_tickets[0]
        ticket_id = ticket["action_id"]

        if is_positive:
            # Authorize ticket
            self.engine.tools.confirm_action(ticket_id)
            reply = f"Action {ticket.get('tool', '')} confirmed and authorized."
            audit_logger.log_event(
                "VOICE_CONFIRMATION_AUTHORIZED",
                action="ticket_confirmed",
                extra={"action_id": ticket_id, "tool": ticket.get("tool")}
            )
            return {
                "success": True,
                "authorized": True,
                "action_id": ticket_id,
                "response": reply,
                "command_type": VoiceCommandType.CONFIRMATION.value,
                "state": self.state_machine.current_state.value
            }
        else:
            # Reject ticket
            if ticket_id in self.engine.tools.pending_confirmations:
                del self.engine.tools.pending_confirmations[ticket_id]
            reply = f"Action {ticket.get('tool', '')} rejected and cancelled."
            audit_logger.log_event(
                "VOICE_CONFIRMATION_CANCELLED",
                action="ticket_rejected",
                extra={"action_id": ticket_id}
            )
            return {
                "success": True,
                "authorized": False,
                "action_id": ticket_id,
                "response": reply,
                "command_type": VoiceCommandType.CONFIRMATION.value,
                "state": self.state_machine.current_state.value
            }

    def _speak_verbal_reply(self, text: str) -> None:
        """Helper to speak a status or response verbally."""
        verbal = summarize_for_voice(text, max_length=MAX_VOICE_SUMMARY_LENGTH)
        self.tts_provider.speak(verbal, async_mode=False)
