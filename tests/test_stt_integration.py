import os

import numpy as np
import pytest

pytestmark = pytest.mark.integration

skip = pytest.mark.skipif(
    os.environ.get("GLIMMER_VOICE_INTEGRATION") != "1",
    reason="set GLIMMER_VOICE_INTEGRATION=1 to run voice integration tests",
)


@skip
def test_tts_stt_roundtrip():
    from assistant.voice.stt import ParakeetSTT
    from assistant.voice.tts import KokoroTTS

    captured = {}
    tts = KokoroTTS("af_heart", player=lambda a, sr: captured.update(audio=np.asarray(a, dtype="float32"), sr=sr))
    tts.speak("the quick brown fox jumps over the lazy dog")

    stt = ParakeetSTT("mlx-community/parakeet-tdt-0.6b-v2")
    transcript = stt.transcribe(captured["audio"], captured["sr"]).lower()

    hits = sum(w in transcript for w in ["quick", "brown", "fox", "lazy", "dog"])
    assert hits >= 3, f"round-trip transcript was: {transcript!r}"
