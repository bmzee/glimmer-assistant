import numpy as np
import pytest

from assistant.voice.audio import HotkeyPushToTalk, assemble


def test_assemble_concatenates_frames():
    out = assemble([np.array([1.0, 2.0], dtype="float32"), np.array([3.0], dtype="float32")])
    assert out.tolist() == [1.0, 2.0, 3.0]


def test_assemble_empty_is_empty_array():
    out = assemble([])
    assert out.size == 0


class FakeRecorder:
    """Records fixed frames while 'active'; driven by the listener fake below."""

    def __init__(self, frames):
        self._frames = frames
        self.buffer = []
        self.active = False

    def start(self):
        self.active = True
        self.buffer.extend(self._frames)  # simulate frames arriving during the hold

    def stop(self):
        self.active = False


def test_run_cycle_returns_audio_when_long_enough():
    rec = FakeRecorder([np.zeros(8000, dtype="float32")])
    ptt = HotkeyPushToTalk(sample_rate=16000, min_seconds=0.3)
    got = ptt._run_cycle(rec, wait_for_release=lambda: None)
    assert got is not None
    audio, sr = got
    assert sr == 16000 and audio.size == 8000


def test_run_cycle_returns_none_when_too_short():
    rec = FakeRecorder([np.zeros(1000, dtype="float32")])  # ~0.06s < 0.3s
    ptt = HotkeyPushToTalk(sample_rate=16000, min_seconds=0.3)
    assert ptt._run_cycle(rec, wait_for_release=lambda: None) is None


def test_invalid_hotkey_raises():
    with pytest.raises(ValueError):
        HotkeyPushToTalk(hotkey="not_a_key")


def test_valid_hotkey_ok():
    HotkeyPushToTalk(hotkey="ctrl")
