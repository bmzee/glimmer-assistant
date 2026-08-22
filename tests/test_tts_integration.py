import os

import numpy as np
import pytest

pytestmark = pytest.mark.integration

skip = pytest.mark.skipif(
    os.environ.get("GLIMMER_VOICE_INTEGRATION") != "1",
    reason="set GLIMMER_VOICE_INTEGRATION=1 to run voice integration tests",
)


@skip
def test_kokoro_produces_nonsilent_audio():
    from assistant.voice.tts import KokoroTTS

    captured = {}
    tts = KokoroTTS("af_heart", player=lambda a, sr: captured.update(audio=np.asarray(a), sr=sr))
    tts.speak("testing the local text to speech engine")
    assert captured["sr"] == 24000
    assert captured["audio"].size > 24000  # >1s of audio
    assert float(np.abs(captured["audio"]).max()) > 0.01  # not silence
