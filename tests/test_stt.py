"""These tests used to assert the WAV round-trip -- the bug itself.

`assert fake.paths[0].endswith(".wav")` locked in handing a file path to
parakeet_mlx, which decodes it by shelling out to ffmpeg. That call fails in a
packaged .app, where launchd's PATH has no /opt/homebrew/bin. The tests passed
throughout, because a fake model never runs ffmpeg.

See tests/test_stt_no_ffmpeg.py for the regression tests that now cover it.
"""
import os

import numpy as np

from assistant.voice.stt import ParakeetSTT


def preprocess_args():
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


class FakeModel:
    def __init__(self, text="  hello world  "):
        self.preprocessor_config = preprocess_args()
        self.mels = []
        self._text = text

    def generate(self, mel, **kw):
        self.mels.append(mel)
        return [type("R", (), {"text": self._text})()]


def test_transcribe_returns_the_models_text_trimmed():
    fake = FakeModel()
    stt = ParakeetSTT("some/model", model=fake)

    assert stt.transcribe(np.zeros(16000, dtype="float32"), 16000) == "hello world"
    assert fake.mels, "the model was never given anything to transcribe"


def test_empty_results_are_not_an_error():
    """A silent clip transcribes to nothing; the session should hear "" and
    move on, not take an exception."""
    class Silent(FakeModel):
        def generate(self, mel, **kw):
            return []

    assert ParakeetSTT("m", model=Silent()).transcribe(np.zeros(1600, "float32"), 16000) == ""


def test_transcribe_does_not_leak_file_descriptors():
    """Kept from when this wrote temp WAVs and leaked the mkstemp fd. There is
    no file handling left to leak, which is the point -- it stays as a guard
    against reintroducing any."""
    def open_fd_count():
        # /dev/fd lists this process's open fds on macOS and Linux
        return len(os.listdir("/dev/fd"))

    stt = ParakeetSTT("m", model=FakeModel(text="hi"))
    stt.transcribe(np.zeros(1600, dtype="float32"), 16000)  # warm one-time fds
    before = open_fd_count()
    for _ in range(50):
        stt.transcribe(np.zeros(1600, dtype="float32"), 16000)

    assert open_fd_count() <= before, "transcribe leaked file descriptors"
