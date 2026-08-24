"""The packaged app could never transcribe, because STT shelled out to ffmpeg.

Reproduced end-to-end: with PATH set to launchd's default -- exactly what a
double-clicked .app inherits, since `launchctl getenv PATH` is empty on this
machine -- the real model loads fine and then:

    RuntimeError: FFmpeg is not installed or not in your PATH.

ffmpeg exists only at /opt/homebrew/bin/ffmpeg, which is not on that PATH. The
session catches the error and says "Sorry, something went wrong.", every turn,
with nothing to diagnose from. ffmpeg is declared nowhere: not in
pyproject.toml, not bundled, not probed by preflight.

Every existing STT test missed it. tests/test_stt.py mocks transcribe, and
tests/test_stt_integration.py only runs under GLIMMER_VOICE_INTEGRATION=1 --
from a shell, where Homebrew is on PATH.

The audio is ALREADY a float32 array in memory. Writing it to a WAV so that a
subprocess can decode it back to an array is pure round-trip, and the binary
that does it is the single undeclared dependency standing between this app and
working at all.
"""
import os

import numpy as np
import pytest

from assistant.voice.stt import ParakeetSTT


class ArrayOnlyModel:
    """Accepts the in-memory path and refuses the file path.

    Mirrors reality: parakeet_mlx's transcribe(path) is the call that reaches
    ffmpeg, so a fake that allows it would let the bug back in unnoticed.
    """

    def __init__(self):
        self.preprocessor_config = _PreprocessArgs()
        self.mels = []

    def transcribe(self, path, *a, **kw):
        raise AssertionError(
            "STT used the file-based API, which shells out to ffmpeg -- "
            "the exact call that fails in a packaged .app"
        )

    def generate(self, mel, **kw):
        self.mels.append(mel)
        return [_Result("hello there")]


def _PreprocessArgs():
    """The real config object, with Parakeet's own values.

    Hand-rolling a stand-in here would be testing a mock: get_logmel reads a
    dozen fields off it, and a fake that happens to satisfy today's reads would
    stop reflecting the library the moment it changes.
    """
    from parakeet_mlx.audio import PreprocessArgs

    return PreprocessArgs(
        sample_rate=16000,
        normalize="per_feature",
        window_size=0.025,
        window_stride=0.01,
        window="hann",
        features=128,
        n_fft=512,
        dither=0.0,
    )


class _Result:
    def __init__(self, text):
        self.text = text


def test_transcribes_from_the_array_without_touching_the_filesystem():
    model = ArrayOnlyModel()
    stt = ParakeetSTT("unused", model=model)

    assert stt.transcribe(np.zeros(16000, dtype="float32"), 16000) == "hello there"
    assert model.mels, "no mel was ever computed"


def test_no_temp_wav_is_written(tmp_path, monkeypatch):
    """The WAV existed only to feed a subprocess that no longer runs."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    stt = ParakeetSTT("unused", model=ArrayOnlyModel())

    stt.transcribe(np.zeros(16000, dtype="float32"), 16000)

    assert not list(tmp_path.iterdir()), f"temp files left behind: {list(tmp_path.iterdir())}"


def test_audio_at_another_rate_is_resampled_rather_than_refused():
    """ffmpeg was doing two jobs, not one: decoding AND resampling.

    Live capture asks CoreAudio for 16kHz so it is usually already right, but
    the TTS->STT round-trip runs at 24kHz and a different input device can
    deliver its own rate. Dropping the resample along with the subprocess would
    trade a packaging bug for an audio bug.
    """
    from assistant.voice.stt import to_model_rate

    assert len(to_model_rate(np.zeros(32000, dtype="float32"), 32000, 16000)) == pytest.approx(
        16000, rel=0.01
    )


def test_audio_already_at_the_model_rate_is_passed_through_untouched():
    """Resampling 16k->16k would cost time and add filter artefacts for nothing."""
    from assistant.voice.stt import to_model_rate

    audio = np.zeros(1600, dtype="float32")
    assert to_model_rate(audio, 16000, 16000) is audio


@pytest.mark.skipif(
    os.environ.get("GLIMMER_VOICE_INTEGRATION") != "1",
    reason="needs the real Parakeet weights; set GLIMMER_VOICE_INTEGRATION=1",
)
def test_real_model_transcribes_on_the_path_a_double_clicked_app_gets(monkeypatch):
    """The regression test for the actual bug, against the real model.

    This is the one that would have caught it: the unit tests above use a fake,
    and a fake cannot prove that the real library stopped needing ffmpeg.
    """
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    import shutil

    assert shutil.which("ffmpeg") is None, "PATH still has ffmpeg; test proves nothing"

    from assistant.config import Config

    stt = ParakeetSTT(Config().voice_stt_model)
    assert isinstance(stt.transcribe(np.zeros(16000, dtype="float32"), 16000), str)
