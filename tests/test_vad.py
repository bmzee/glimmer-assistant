"""Hands-free capture: speak, stop, and it answers. No clicking.

Click-speak-click is worse than a hotkey, and it was only chosen because the
hotkey needed a permission macOS would not grant. With the app listening
continuously, an utterance is bounded by speech itself: it begins when you
start talking and ends when you stop.

The hard part is not detecting speech, it is deciding when you have FINISHED.
Cut too early and you truncate mid-sentence; cut too late and every reply feels
laggy. So the end is a run of silence, not a single quiet frame.
"""
import numpy as np

from assistant.voice.vad import VoiceActivityCapture


def frames(*specs):
    """Build frames: (amplitude, count) pairs, 0.1s each at 16 kHz."""
    out = []
    for amp, count in specs:
        for _ in range(count):
            out.append(np.full(1600, amp, dtype="float32"))
    return out


class ScriptedRecorder:
    """Replays a fixed frame sequence as if it were arriving live."""

    def __init__(self, sample_rate, script=None):
        self.sample_rate = sample_rate
        self._script = list(script or [])
        self.buffer = []
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def pump(self):
        """Deliver one frame; returns False when the script is exhausted."""
        if not self._script:
            return False
        self.buffer.append(self._script.pop(0))
        return True


def _capture(script, **kw):
    rec = ScriptedRecorder(16000, script)
    cap = VoiceActivityCapture(
        recorder_factory=lambda sr: rec,
        pump=rec.pump,
        **kw,
    )
    return cap, rec


def test_speech_then_silence_produces_an_utterance():
    script = frames((0.0, 3), (0.4, 10), (0.0, 12))
    cap, _ = _capture(script, silence_seconds=0.6, min_seconds=0.3)
    result = cap.capture_utterance()
    assert result is not None
    audio, sr = result
    assert sr == 16000 and audio.size > 0


def test_silence_alone_never_produces_a_turn():
    """A quiet room must not trigger the assistant every few seconds."""
    cap, _ = _capture(frames((0.0, 40)), silence_seconds=0.6)
    assert cap.capture_utterance() is None


def test_a_brief_noise_is_not_treated_as_speech():
    """A door closing is loud and short; it must not start a turn."""
    cap, _ = _capture(frames((0.0, 3), (0.5, 1), (0.0, 20)),
                      silence_seconds=0.6, min_seconds=0.5)
    assert cap.capture_utterance() is None


def test_a_pause_mid_sentence_does_not_cut_the_utterance():
    """People pause to think. A short gap is part of one request, not two."""
    script = frames((0.4, 6), (0.0, 3), (0.4, 6), (0.0, 12))
    cap, _ = _capture(script, silence_seconds=0.8, min_seconds=0.3)
    result = cap.capture_utterance()
    assert result is not None
    # Both halves plus the gap: cutting at the pause would return far less.
    assert result[0].size >= 15 * 1600 * 0.8


def test_utterance_is_bounded_even_if_someone_never_stops():
    cap, _ = _capture(frames((0.4, 200)), max_seconds=1.0, silence_seconds=0.6)
    result = cap.capture_utterance()
    assert result is not None
    assert result[0].size <= int(1.2 * 16000)


def test_recorder_is_always_stopped():
    cap, rec = _capture(frames((0.4, 5), (0.0, 12)), silence_seconds=0.6)
    cap.capture_utterance()
    assert rec.started == rec.stopped


def test_shutdown_unblocks_a_waiting_capture():
    cap, _ = _capture(frames((0.0, 5)))
    cap.shutdown()
    assert cap.capture_utterance() is None


def test_reports_listening_state_for_the_ui():
    cap, _ = _capture(frames((0.4, 5), (0.0, 12)), silence_seconds=0.6)
    assert cap.is_listening is False
    cap.capture_utterance()
    assert cap.is_listening is False
