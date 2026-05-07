"""Piper TTS voice synthesis - no temp files, no popups."""

import io
import os
import wave
import base64
import winsound
from pathlib import Path
from typing import Optional

from piper import PiperVoice


class VoiceEngine:
    """Local Piper TTS with zero file I/O."""

    def __init__(self, model_name: str = "en_US-lessac-medium"):
        self.model_name = model_name
        self._voice: Optional[PiperVoice] = None
        self._model_path: Optional[Path] = None
        self._ensure_model()

    def _ensure_model(self):
        """Download model if not present."""
        model_dir = Path.home() / ".local" / "share" / "piper"
        model_dir.mkdir(parents=True, exist_ok=True)
        self._model_path = model_dir / f"{self.model_name}.onnx"
        config_path = model_dir / f"{self.model_name}.onnx.json"

        if not self._model_path.exists() or not config_path.exists():
            self._download_model(model_dir)

        if not self._voice:
            self._voice = PiperVoice.load(str(self._model_path))

    def _download_model(self, model_dir: Path):
        """Download voice model from HuggingFace."""
        import urllib.request
        base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/"
        files = [f"{self.model_name}.onnx", f"{self.model_name}.onnx.json"]

        for f in files:
            path = model_dir / f
            if path.exists():
                continue
            print(f"[Voice] Downloading {f}...")
            urllib.request.urlretrieve(base_url + f, str(path))
            print(f"[Voice] Downloaded {f}")

    def synthesize(self, text: str) -> bytes:
        """Generate WAV audio bytes from text. Returns full WAV file bytes."""
        if not self._voice:
            self._ensure_model()

        audio_buf = io.BytesIO()
        with wave.open(audio_buf, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)

            for chunk in self._voice.synthesize(text):
                wav_file.writeframes(chunk.audio_int16_bytes)

        return audio_buf.getvalue()

    def synthesize_base64(self, text: str) -> str:
        """Generate base64-encoded WAV for web transport."""
        wav_bytes = self.synthesize(text)
        return base64.b64encode(wav_bytes).decode('utf-8')

    def play(self, text: str):
        """Speak text immediately via system audio (CLI mode)."""
        wav_bytes = self.synthesize(text)
        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)

    def play_bytes(self, wav_bytes: bytes):
        """Play raw WAV bytes immediately."""
        winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)


# Global voice engine instance
_voice_engine: Optional[VoiceEngine] = None


def get_voice() -> VoiceEngine:
    """Get or create global voice engine."""
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine()
    return _voice_engine
