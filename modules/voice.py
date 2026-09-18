"""
ZARA Voice Module: Bidirectional Voice Interface (STT -> Reasoning -> TTS).
Preserves macOS native high-quality female TTS (Samantha) with pluggable STT and speech interruption.
"""
import subprocess
import shutil
import os
import threading
import time
from typing import Optional, Callable
from config.settings import ENABLE_VOICE, VOICE_NAME, VOICE_RATE

class VoiceSynthesizer:
    def __init__(self, voice_name: str = VOICE_NAME, rate: int = VOICE_RATE, enabled: bool = ENABLE_VOICE):
        self.voice_name = voice_name
        self.rate = rate
        self.enabled = enabled
        self._say_path = shutil.which("say")
        self._current_process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()

    def interrupt(self) -> None:
        """Interrupt any currently playing speech."""
        with self._lock:
            if self._current_process and self._current_process.poll() is None:
                self._current_process.terminate()
                self._current_process = None

    def speak(self, text: str, async_mode: bool = True) -> None:
        """Speak a status update, summary, or response using a female voice."""
        if not self.enabled or not text.strip():
            return

        clean_text = self._sanitize_text(text)
        self.interrupt()

        if async_mode:
            thread = threading.Thread(target=self._speak_sync, args=(clean_text,), daemon=True)
            thread.start()
        else:
            self._speak_sync(clean_text)

    def _sanitize_text(self, text: str) -> str:
        """Strip markdown markers and code blocks for clean auditory speech."""
        import re
        clean = re.sub(r"```.*?```", "code block omitted", text, flags=re.DOTALL)
        clean = re.sub(r"`([^`]+)`", r"\1", clean)
        clean = re.sub(r"[#*_~>\[\]]", "", clean)
        clean = re.sub(r"https?://\S+", "link", clean)
        return clean.strip()

    def _speak_sync(self, text: str) -> None:
        # ElevenLabs API override if configured
        elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        if elevenlabs_key:
            try:
                self._speak_elevenlabs(text, elevenlabs_key)
                return
            except Exception:
                pass

        # macOS native female TTS (Samantha)
        if self._say_path:
            try:
                with self._lock:
                    self._current_process = subprocess.Popen(
                        [self._say_path, "-v", self.voice_name, "-r", str(self.rate), text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                self._current_process.wait()
                return
            except Exception:
                pass

    def _speak_elevenlabs(self, text: str, api_key: str) -> None:
        import urllib.request
        import json
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
        data = json.dumps({"text": text, "model_id": "eleven_monolingual_v1"}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req) as resp:
            audio_content = resp.read()
            afplay = shutil.which("afplay")
            if afplay:
                tmp_path = "/tmp/zara_speech.mp3"
                with open(tmp_path, "wb") as f:
                    f.write(audio_content)
                subprocess.run([afplay, tmp_path], check=False)

class SpeechToTextAdapter:
    """Microphone / Speech-to-Text input adapter."""
    def __init__(self):
        self.available = False

    def listen(self, timeout_seconds: int = 5) -> Optional[str]:
        """Listen from microphone if speech_recognition or whisper installed, else return None."""
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.Microphone() as source:
                audio = r.listen(source, timeout=timeout_seconds, phrase_time_limit=15)
                return r.recognize_google(audio)
        except Exception:
            return None
