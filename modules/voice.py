"""
ZARA Voice Module: Production-Quality Voice Interaction Layer.
Provides Speech-To-Text (STT), Text-To-Speech (TTS), and Voice Activity Detection (VAD)
abstractions, observable state machine, wake-word activation, voice command classification,
barge-in interruption, and temporary audio lifecycle cleanup.
"""
from abc import ABC, abstractmethod
import datetime
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Optional, Callable, Dict, Any, List, Tuple, Union

from config.settings import (
    ENABLE_VOICE,
    VOICE_NAME,
    VOICE_RATE,
    WAKE_WORD,
    MAX_RECORDING_SECONDS,
    VOICE_SILENCE_TIMEOUT,
    TTS_ENABLED,
    STT_PROVIDER,
    TTS_PROVIDER,
    VOICE_LANGUAGE,
    MAX_VOICE_SUMMARY_LENGTH,
    VOICE_TEMP_DIR,
    LOGS_DIR
)
from core.state import (
    VoiceState,
    VoiceCommandType,
    TranscriptionResult,
    AudioResult,
    VoiceActivityResult,
    VoiceClassificationResult,
    RiskLevel
)
from core.observability import audit_logger


# =====================================================================
# 1. AUDIO LIFECYCLE & PRIVACY MANAGER
# =====================================================================

class VoiceAudioLifecycle:
    """Manages temporary audio buffers, preventing continuous or unauthorized audio retention."""

    def __init__(self, temp_dir: Path = VOICE_TEMP_DIR):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._tracked_files: List[Path] = []
        self._lock = threading.Lock()

    def get_temp_audio_path(self, prefix: str = "voice", suffix: str = ".wav") -> Path:
        """Create a deterministic temporary audio file path within the designated voice temp directory."""
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.temp_dir / f"{prefix}_{ts}{suffix}"
        with self._lock:
            self._tracked_files.append(path)
        return path

    def delete_file(self, path: Union[str, Path]) -> bool:
        """Immediately delete a temporary audio file."""
        p = Path(path)
        try:
            if p.exists():
                p.unlink()
            with self._lock:
                if p in self._tracked_files:
                    self._tracked_files.remove(p)
            return True
        except OSError:
            return False

    def cleanup_temp_files(self) -> int:
        """Clean up all tracked or stale temporary audio files in the temp directory."""
        cleaned = 0
        with self._lock:
            for p in list(self._tracked_files):
                try:
                    if p.exists():
                        p.unlink()
                        cleaned += 1
                except OSError:
                    pass
            self._tracked_files.clear()

        # Also purge any dangling audio files in the voice temp dir
        if self.temp_dir.exists():
            for f in self.temp_dir.glob("voice_*.*"):
                try:
                    if f.is_file():
                        f.unlink()
                        cleaned += 1
                except OSError:
                    pass
        return cleaned


# Global lifecycle instance
voice_lifecycle = VoiceAudioLifecycle()


# =====================================================================
# 2. VOICE STATE MACHINE
# =====================================================================

class VoiceStateMachine:
    """
    Observable finite state machine governing ZARA's voice interaction states.
    Validates state transitions and emits audit logs for observability.
    """

    ALLOWED_TRANSITIONS: Dict[VoiceState, List[VoiceState]] = {
        VoiceState.IDLE: [VoiceState.LISTENING, VoiceState.THINKING, VoiceState.ERROR],
        VoiceState.LISTENING: [VoiceState.TRANSCRIBING, VoiceState.IDLE, VoiceState.INTERRUPTED, VoiceState.ERROR],
        VoiceState.TRANSCRIBING: [VoiceState.THINKING, VoiceState.IDLE, VoiceState.ERROR],
        VoiceState.THINKING: [VoiceState.ACTING, VoiceState.SPEAKING, VoiceState.IDLE, VoiceState.ERROR],
        VoiceState.ACTING: [VoiceState.SPEAKING, VoiceState.THINKING, VoiceState.IDLE, VoiceState.ERROR],
        VoiceState.SPEAKING: [VoiceState.IDLE, VoiceState.INTERRUPTED, VoiceState.ERROR, VoiceState.LISTENING],
        VoiceState.INTERRUPTED: [VoiceState.IDLE, VoiceState.LISTENING],
        VoiceState.ERROR: [VoiceState.IDLE]
    }

    def __init__(self, initial_state: VoiceState = VoiceState.IDLE):
        self._state: VoiceState = initial_state
        self._lock = threading.Lock()
        self._history: List[Tuple[VoiceState, float]] = [(initial_state, time.time())]

    @property
    def current_state(self) -> VoiceState:
        with self._lock:
            return self._state

    def transition_to(self, new_state: VoiceState, reason: str = "") -> bool:
        """
        Transition to new_state if valid under ALLOWED_TRANSITIONS.
        Returns True on success, False if the transition is invalid.
        """
        with self._lock:
            current = self._state
            if new_state == current:
                return True

            allowed = self.ALLOWED_TRANSITIONS.get(current, [])
            if new_state not in allowed:
                audit_logger.log_event(
                    "VOICE_STATE_INVALID_TRANSITION",
                    action="transition_rejected",
                    extra={"from_state": current.value, "to_state": new_state.value, "reason": reason}
                )
                return False

            self._state = new_state
            self._history.append((new_state, time.time()))

        audit_logger.log_event(
            "VOICE_STATE_TRANSITION",
            action="state_change",
            extra={"from_state": current.value, "to_state": new_state.value, "reason": reason}
        )
        return True

    def reset(self) -> None:
        """Force reset to IDLE."""
        with self._lock:
            self._state = VoiceState.IDLE
            self._history.append((VoiceState.IDLE, time.time()))


# =====================================================================
# 3. PROVIDER INTERFACES (ABCs)
# =====================================================================

class SpeechToTextProvider(ABC):
    """Abstract interface for Speech-to-Text providers."""

    @abstractmethod
    def transcribe(self, audio_input: Any, **kwargs) -> TranscriptionResult:
        """Transcribe speech audio (bytes, path, or stream) into structured text."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether provider and hardware/library are accessible."""
        pass


class TextToSpeechProvider(ABC):
    """Abstract interface for Text-to-Speech providers."""

    @abstractmethod
    def synthesize(self, text: str, output_path: Optional[str] = None) -> AudioResult:
        """Synthesize text into speech audio data."""
        pass

    @abstractmethod
    def speak(self, text: str, async_mode: bool = True) -> bool:
        """Play synthesized speech audio aloud."""
        pass

    @abstractmethod
    def interrupt(self) -> None:
        """Stop any active audio playback immediately."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether TTS output device or service is available."""
        pass


class VoiceActivityDetector(ABC):
    """Abstract interface for Voice Activity Detection (VAD)."""

    @abstractmethod
    def detect_speech(self, audio_chunk: bytes) -> VoiceActivityResult:
        """Analyze a PCM audio chunk for speech activity."""
        pass


# =====================================================================
# 4. CONCRETE STT PROVIDERS
# =====================================================================

class MockSTTProvider(SpeechToTextProvider):
    """Deterministic, configurable mock STT provider for offline unit and integration tests."""

    def __init__(self, default_text: str = "ZARA, status report", default_confidence: float = 0.95):
        self.default_text = default_text
        self.default_confidence = default_confidence
        self.simulated_error: Optional[str] = None
        self.simulated_delay: float = 0.0
        self.available: bool = True

    def set_transcription(self, text: str, confidence: float = 0.95) -> None:
        """Queue the next transcription return value."""
        self.default_text = text
        self.default_confidence = confidence
        self.simulated_error = None

    def set_error(self, error: str) -> None:
        """Queue a simulated STT error."""
        self.simulated_error = error

    def is_available(self) -> bool:
        return self.available

    def transcribe(self, audio_input: Any, **kwargs) -> TranscriptionResult:
        if self.simulated_delay > 0:
            time.sleep(self.simulated_delay)

        if not self.available:
            return TranscriptionResult(
                success=False,
                text="",
                confidence=0.0,
                error="Microphone or STT provider is unavailable"
            )

        if self.simulated_error:
            return TranscriptionResult(
                success=False,
                text="",
                confidence=0.0,
                error=self.simulated_error
            )

        # If audio_input is a string representing text, we can echo or use default
        text = str(audio_input) if isinstance(audio_input, str) and not Path(audio_input).exists() else self.default_text

        return TranscriptionResult(
            success=True,
            text=text,
            confidence=self.default_confidence,
            duration_seconds=1.2,
            language="en-US"
        )


class LocalSTTProvider(SpeechToTextProvider):
    """Offline STT provider using SpeechRecognition or Whisper if installed."""

    def __init__(self):
        self._sr = None
        try:
            import speech_recognition as sr
            self._sr = sr
        except ImportError:
            self._sr = None

    def is_available(self) -> bool:
        return self._sr is not None

    def transcribe(self, audio_input: Any, **kwargs) -> TranscriptionResult:
        if not self.is_available():
            return TranscriptionResult(
                success=False,
                text="",
                confidence=0.0,
                error="SpeechRecognition library not installed. Please install 'SpeechRecognition' or use mock provider."
            )

        try:
            r = self._sr.Recognizer()
            if isinstance(audio_input, (str, Path)) and Path(audio_input).exists():
                with self._sr.AudioFile(str(audio_input)) as source:
                    audio = r.record(source)
                    text = r.recognize_google(audio)
                    return TranscriptionResult(success=True, text=text, confidence=0.88, language="en-US")
            else:
                return TranscriptionResult(success=False, text="", error="Invalid audio file input")
        except Exception as e:
            return TranscriptionResult(success=False, text="", error=f"Local STT failed: {str(e)}")


# =====================================================================
# 5. CONCRETE TTS PROVIDERS
# =====================================================================

class MockTTSProvider(TextToSpeechProvider):
    """Deterministic, silent in-memory mock TTS provider for testing."""

    def __init__(self):
        self.synthesized_utterances: List[str] = []
        self.is_speaking_state: bool = False
        self.interrupted_count: int = 0
        self.available: bool = True
        self.simulated_error: Optional[str] = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return self.available

    def synthesize(self, text: str, output_path: Optional[str] = None) -> AudioResult:
        if not self.available or self.simulated_error:
            return AudioResult(
                success=False,
                error=self.simulated_error or "Audio output device unavailable"
            )

        with self._lock:
            self.synthesized_utterances.append(text)

        target_path = output_path
        if not target_path:
            p = voice_lifecycle.get_temp_audio_path(prefix="mock_tts", suffix=".wav")
            p.write_bytes(b"RIFFmockwavheader")
            target_path = str(p)

        return AudioResult(
            success=True,
            audio_bytes=b"RIFFmockdata",
            audio_path=target_path,
            duration_seconds=len(text) * 0.05
        )

    def speak(self, text: str, async_mode: bool = True) -> bool:
        if not self.available or self.simulated_error:
            return False
        with self._lock:
            self.synthesized_utterances.append(text)
            self.is_speaking_state = True
        return True

    def interrupt(self) -> None:
        with self._lock:
            self.is_speaking_state = False
            self.interrupted_count += 1


class NativeMacOSTTSProvider(TextToSpeechProvider):
    """Native macOS speech synthesis via the 'say' command with PID tracking and interruptibility."""

    def __init__(self, voice_name: str = VOICE_NAME, rate: int = VOICE_RATE):
        self.voice_name = voice_name
        self.rate = rate
        self._say_path = shutil.which("say")
        self._current_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return self._say_path is not None

    def interrupt(self) -> None:
        """Immediately terminate active macOS say subprocess."""
        with self._lock:
            if self._current_process and self._current_process.poll() is None:
                try:
                    self._current_process.terminate()
                    self._current_process.wait(timeout=0.5)
                except (subprocess.TimeoutExpired, OSError):
                    try:
                        self._current_process.kill()
                    except OSError:
                        pass
                finally:
                    self._current_process = None

    def synthesize(self, text: str, output_path: Optional[str] = None) -> AudioResult:
        if not self.is_available():
            return AudioResult(success=False, error="macOS 'say' command not found")

        out_path = Path(output_path) if output_path else voice_lifecycle.get_temp_audio_path(prefix="macos_tts", suffix=".aiff")
        try:
            subprocess.run(
                [self._say_path, "-v", self.voice_name, "-r", str(self.rate), "-o", str(out_path), text],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return AudioResult(
                success=True,
                audio_path=str(out_path),
                duration_seconds=max(0.5, len(text) * 0.06)
            )
        except Exception as e:
            return AudioResult(success=False, error=f"macOS synthesis failed: {str(e)}")

    def speak(self, text: str, async_mode: bool = True) -> bool:
        if not self.is_available() or not text.strip():
            return False

        self.interrupt()

        if async_mode:
            t = threading.Thread(target=self._run_say, args=(text,), daemon=True)
            t.start()
            return True
        else:
            return self._run_say(text)

    def _run_say(self, text: str) -> bool:
        try:
            with self._lock:
                self._current_process = subprocess.Popen(
                    [self._say_path, "-v", self.voice_name, "-r", str(self.rate), text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            self._current_process.wait()
            with self._lock:
                self._current_process = None
            return True
        except Exception:
            with self._lock:
                self._current_process = None
            return False


# =====================================================================
# 6. CONCRETE VAD PROVIDERS
# =====================================================================

class MockVADProvider(VoiceActivityDetector):
    """Deterministic mock VAD for unit testing speech-start and speech-end transitions."""

    def __init__(self, sequence: Optional[List[bool]] = None):
        self.sequence = sequence if sequence is not None else [True, True, False]
        self._index = 0

    def detect_speech(self, audio_chunk: bytes) -> VoiceActivityResult:
        if not self.sequence:
            return VoiceActivityResult(is_speech=False, energy=0.0, confidence=1.0)
        
        is_speech = self.sequence[self._index % len(self.sequence)]
        self._index += 1
        energy = 0.8 if is_speech else 0.05
        return VoiceActivityResult(is_speech=is_speech, energy=energy, confidence=0.9)


class EnergyVADProvider(VoiceActivityDetector):
    """RMS energy threshold detector for raw 16-bit PCM audio chunks."""

    def __init__(self, threshold: float = 0.02):
        self.threshold = threshold

    def detect_speech(self, audio_chunk: bytes) -> VoiceActivityResult:
        if not audio_chunk:
            return VoiceActivityResult(is_speech=False, energy=0.0, confidence=1.0)

        # Compute root mean square
        import struct
        count = len(audio_chunk) // 2
        if count == 0:
            return VoiceActivityResult(is_speech=False, energy=0.0, confidence=1.0)

        try:
            shorts = struct.unpack(f"{count}h", audio_chunk[:count * 2])
            sum_squares = sum(s * s for s in shorts)
            rms = math.sqrt(sum_squares / count) / 32768.0
            is_speech = rms >= self.threshold
            return VoiceActivityResult(is_speech=is_speech, energy=rms, confidence=0.85)
        except Exception:
            return VoiceActivityResult(is_speech=False, energy=0.0, confidence=0.5)


# =====================================================================
# 7. UTILITY & CLASSIFICATION FUNCTIONS
# =====================================================================

def detect_wake_word(text: str, wake_word: str = WAKE_WORD) -> Tuple[bool, str]:
    """
    Detect whether text begins with the configurable wake word.
    Returns (is_wake_detected, cleaned_command).
    """
    cleaned = text.strip()
    # Match wake word at start, with optional "hey", "hi", "hello" prefixes
    pattern = rf"^(?:hey\s+|hi\s+|hello\s+)?{re.escape(wake_word)}[,:\s]*"
    match = re.match(pattern, cleaned, flags=re.IGNORECASE)
    if match:
        remainder = cleaned[match.end():].strip()
        return True, remainder
    return False, cleaned


def classify_voice_input(text: str, context: Optional[Any] = None) -> VoiceClassificationResult:
    """
    Classify transcribed voice text into VoiceCommandType:
    COMMAND, QUESTION, FOLLOW_UP, CANCELLATION, CONFIRMATION.
    """
    is_wake, clean = detect_wake_word(text)
    clean_lower = clean.lower().strip()

    # 1. Cancellation / Stop
    cancellation_phrases = ["stop", "cancel", "abort", "shut up", "halt", "pause", "be quiet", "quit"]
    if clean_lower in cancellation_phrases or any(clean_lower.startswith(p) for p in ["stop ", "cancel "]):
        return VoiceClassificationResult(
            command_type=VoiceCommandType.CANCELLATION,
            clean_text=clean,
            is_wake=is_wake,
            confidence=0.98
        )

    # 2. Confirmation / Rejection
    confirmation_phrases = ["yes", "confirm", "proceed", "go ahead", "do it", "sure", "affirmative", "authorized", "authorize"]
    rejection_phrases = ["no", "deny", "reject", "don't", "do not", "negative"]
    
    first_token = re.split(r"[,:\s]+", clean_lower)[0] if clean_lower else ""
    if clean_lower in confirmation_phrases or first_token in confirmation_phrases or any(clean_lower.startswith(p) for p in confirmation_phrases):
        return VoiceClassificationResult(
            command_type=VoiceCommandType.CONFIRMATION,
            clean_text=clean,
            is_wake=is_wake,
            confidence=0.95,
            requires_confirmation=False
        )
    if clean_lower in rejection_phrases or first_token in rejection_phrases or any(clean_lower.startswith(p) for p in rejection_phrases):
        return VoiceClassificationResult(
            command_type=VoiceCommandType.CONFIRMATION,
            clean_text=clean,
            is_wake=is_wake,
            confidence=0.95,
            requires_confirmation=False
        )

    # 3. Follow-up intent
    follow_up_prefixes = ["also", "and", "add", "now", "after that", "plus", "next", "then"]
    if any(clean_lower.startswith(p + " ") for p in follow_up_prefixes):
        return VoiceClassificationResult(
            command_type=VoiceCommandType.FOLLOW_UP,
            clean_text=clean,
            is_wake=is_wake,
            confidence=0.88
        )

    # 4. Question intent
    question_prefixes = ["what", "who", "where", "when", "why", "how", "can you", "could you", "tell me", "explain", "is it", "are you", "status"]
    if clean_lower.endswith("?") or any(clean_lower.startswith(q) for q in question_prefixes):
        return VoiceClassificationResult(
            command_type=VoiceCommandType.QUESTION,
            clean_text=clean,
            is_wake=is_wake,
            confidence=0.92
        )

    # 5. Default to COMMAND
    return VoiceClassificationResult(
        command_type=VoiceCommandType.COMMAND,
        clean_text=clean,
        is_wake=is_wake,
        confidence=0.90
    )


def summarize_for_voice(text: str, max_length: int = MAX_VOICE_SUMMARY_LENGTH) -> str:
    """
    Format and concisely summarize verbose text, reports, or logs for spoken voice output.
    Strips raw markdown, code blocks, and URLs, offering a verbal summary.
    """
    if not text:
        return ""

    # Strip code blocks
    clean = re.sub(r"```.*?```", "code omitted", text, flags=re.DOTALL)
    # Strip inline code
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    # Strip markdown headers, bullets, bold, italics
    clean = re.sub(r"[#*_~>\[\]]", "", clean)
    # Strip URLs
    clean = re.sub(r"https?://\S+", "link", clean)
    # Normalize whitespace
    clean = re.sub(r"\s+", " ", clean).strip()

    if len(clean) <= max_length:
        return clean

    # Extract first sentence or truncate at word boundary
    first_sentence_match = re.match(r"^(.*?[.!?])(?:\s|$)", clean)
    if first_sentence_match and len(first_sentence_match.group(1)) <= max_length:
        summary_core = first_sentence_match.group(1)
    else:
        # Cut cleanly at nearest word boundary
        truncated = clean[:max_length - 40]
        summary_core = truncated.rsplit(" ", 1)[0] + "."

    return f"{summary_core} I have the complete details ready if you would like me to review them."


# =====================================================================
# 8. BACKWARD COMPATIBILITY: VoiceSynthesizer & SpeechToTextAdapter
# =====================================================================

class VoiceSynthesizer:
    """
    Backward-compatible VoiceSynthesizer interface used across tests and core engine.
    Delegates to active TextToSpeechProvider with female voice (Samantha) default.
    """

    def __init__(
        self,
        voice_name: str = VOICE_NAME,
        rate: int = VOICE_RATE,
        enabled: bool = ENABLE_VOICE,
        provider: Optional[TextToSpeechProvider] = None
    ):
        self.voice_name = voice_name
        self.rate = rate
        self.enabled = enabled
        if provider is not None:
            self.provider = provider
        elif TTS_PROVIDER == "mock":
            self.provider = MockTTSProvider()
        else:
            self.provider = NativeMacOSTTSProvider(voice_name=voice_name, rate=rate)

    def interrupt(self) -> None:
        """Interrupt active speech."""
        self.provider.interrupt()

    def speak(self, text: str, async_mode: bool = True) -> None:
        """Speak sanitized text aloud."""
        if not self.enabled or not text.strip():
            return
        clean_text = self._sanitize_text(text)
        self.provider.speak(clean_text, async_mode=async_mode)

    def _sanitize_text(self, text: str) -> str:
        """Strip markdown markers and code blocks for clean auditory speech."""
        return summarize_for_voice(text, max_length=9999)


class SpeechToTextAdapter:
    """Backward-compatible Speech-to-Text input adapter."""

    def __init__(self, provider: Optional[SpeechToTextProvider] = None):
        self.provider = provider or (MockSTTProvider() if STT_PROVIDER == "mock" else LocalSTTProvider())

    @property
    def available(self) -> bool:
        return self.provider.is_available()

    def listen(self, timeout_seconds: int = 5) -> Optional[str]:
        res = self.provider.transcribe("sample input")
        return res.text if res.success else None
