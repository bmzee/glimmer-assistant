from __future__ import annotations

import threading

from assistant.voice.models import ensure_kokoro_models

# kokoro_onnx phonemizes through the module-level ``phonemizer.phonemize()``,
# which builds a fresh espeak backend on *every* call. Measured on an M3 Max
# that is a flat ~1.79s per utterance regardless of input length (3 characters
# cost the same as 97), and it dominated the spec SS9 voice-latency budget --
# 1.80s of a 2.05s synthesis. A long-lived backend costs ~2.3s to build once
# and then phonemizes in ~0.1ms. See docs/latency.md.
_backends: dict[str, object] = {}
_backends_lock = threading.Lock()


def _espeak_backend(lang: str):
    """Return a process-wide espeak backend for ``lang``, building it once."""
    with _backends_lock:
        backend = _backends.get(lang)
        if backend is None:
            # Importing kokoro_onnx.tokenizer first lets espeakng_loader point
            # phonemizer at the bundled espeak-ng shared library.
            import kokoro_onnx.tokenizer  # noqa: F401
            from phonemizer.backend import EspeakBackend

            backend = EspeakBackend(
                lang, preserve_punctuation=True, with_stress=True
            )
            _backends[lang] = backend
        return backend


class KokoroTTS:
    def __init__(self, voice: str, *, kokoro=None, player=None, phonemizer=None):
        if kokoro is None:
            from kokoro_onnx import Kokoro

            onnx_path, voices_path = ensure_kokoro_models()
            kokoro = Kokoro(str(onnx_path), str(voices_path))
        self._kokoro = kokoro
        self._voice = voice
        self._play = player or self._default_player
        # Injectable for tests: callable(text, lang) -> phoneme string.
        self._phonemizer = phonemizer

    @staticmethod
    def _default_player(audio, sample_rate: int) -> None:
        import sounddevice

        sounddevice.play(audio, sample_rate)
        sounddevice.wait()

    def _phonemes(self, text: str, lang: str) -> str | None:
        """Phonemize via the long-lived backend, mirroring kokoro_onnx exactly.

        Returns None if the fast path is unavailable for any reason, in which
        case the caller falls back to letting kokoro_onnx phonemize itself.
        Correctness matters more here than the 1.8s: kokoro normalizes the text
        first and then drops any phoneme outside its vocab, so we must do both
        or the model receives tokens it was never trained on.
        """
        try:
            if self._phonemizer is not None:
                raw = self._phonemizer(text, lang)
            else:
                from kokoro_onnx.tokenizer import Tokenizer

                raw = _espeak_backend(lang).phonemize(
                    [Tokenizer.normalize_text(text)]
                )[0]
            vocab = self._kokoro.tokenizer.vocab
            return "".join(p for p in raw if p in vocab).strip()
        except Exception:
            return None

    def speak(self, text: str) -> None:
        lang = "en-us"
        phonemes = self._phonemes(text, lang)
        if phonemes:
            audio, sample_rate = self._kokoro.create(
                phonemes, voice=self._voice, speed=1.0, lang=lang, is_phonemes=True
            )
        else:
            audio, sample_rate = self._kokoro.create(
                text, voice=self._voice, speed=1.0, lang=lang
            )
        self._play(audio, sample_rate)
