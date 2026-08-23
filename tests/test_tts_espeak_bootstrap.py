"""The espeak backend must configure itself, not rely on construction order.

kokoro_onnx calls EspeakWrapper.set_library() inside Tokenizer.__init__, NOT at
module import. So `import kokoro_onnx.tokenizer` does not make phonemizer usable
-- the library path is only set as a side effect of constructing a Kokoro
instance.

Today production works purely by ordering luck: KokoroTTS.__init__ builds a
Kokoro before speak() ever calls _espeak_backend(). If that order shifts (a
bundled app, an injected kokoro, a caller that warms the backend early), the
fast path raises, is swallowed by the fallback, and TTS silently reverts to
~1.9s per utterance with no error -- undoing the fix in 8835aa7 invisibly.

Run in a subprocess: EspeakWrapper's configuration is process-global, so any
other test that touched Kokoro first would mask the bug in-process.
"""
import subprocess
import sys
import textwrap


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True, text=True, timeout=300,
    )


def test_backend_works_without_a_kokoro_instance_existing_first():
    """Fails before the fix with 'espeak not installed on your system'."""
    result = _run(
        """
        from assistant.voice.tts import _espeak_backend
        backend = _espeak_backend("en-us")
        out = backend.phonemize(["hello there"])[0]
        assert out.strip(), "phonemizer returned nothing"
        print("PHONEMES_OK", out.strip()[:40])
        """
    )
    assert "PHONEMES_OK" in result.stdout, (
        f"backend could not phonemize without a prior Kokoro.\n"
        f"stdout={result.stdout}\nstderr={result.stderr[-800:]}"
    )


def test_speak_uses_the_fast_path_not_the_silent_fallback():
    """The fallback is correct but slow; a silent downgrade must be detectable.

    Asserts create() is reached with is_phonemes=True, which only happens when
    phonemization actually succeeded.
    """
    result = _run(
        """
        from assistant.voice.tts import KokoroTTS

        seen = {}

        class RecordingKokoro:
            class tokenizer:
                vocab = set("abcdefghijklmnopqrstuvwxyz ehloItD\\u02c8\\u02d0\\u027e\\u026a\\u014b")
            def create(self, text, voice, speed=1.0, lang="en-us",
                       is_phonemes=False, trim=True):
                seen["is_phonemes"] = is_phonemes
                seen["text"] = text
                return ([0.0], 24000)

        KokoroTTS("af_heart", kokoro=RecordingKokoro(),
                  player=lambda a, sr: None).speak("hello there")
        assert seen.get("is_phonemes") is True, f"fell back to slow path: {seen}"
        print("FAST_PATH_OK")
        """
    )
    assert "FAST_PATH_OK" in result.stdout, (
        f"speak() silently used the slow phonemization path.\n"
        f"stdout={result.stdout}\nstderr={result.stderr[-800:]}"
    )
