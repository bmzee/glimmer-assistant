from __future__ import annotations

from assistant.voice.models import ensure_kokoro_models


class KokoroTTS:
    def __init__(self, voice: str, *, kokoro=None, player=None):
        if kokoro is None:
            from kokoro_onnx import Kokoro

            onnx_path, voices_path = ensure_kokoro_models()
            kokoro = Kokoro(str(onnx_path), str(voices_path))
        self._kokoro = kokoro
        self._voice = voice
        self._play = player or self._default_player

    @staticmethod
    def _default_player(audio, sample_rate: int) -> None:
        import sounddevice

        sounddevice.play(audio, sample_rate)
        sounddevice.wait()

    def speak(self, text: str) -> None:
        audio, sample_rate = self._kokoro.create(
            text, voice=self._voice, speed=1.0, lang="en-us"
        )
        self._play(audio, sample_rate)
