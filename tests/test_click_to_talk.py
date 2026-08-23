"""Click-driven capture: no global hotkey, therefore no Input Monitoring.

The push-to-talk hotkey needs Input Monitoring, which macOS gates and which,
ungranted, makes the app look completely dead. A button inside our own UI needs
no permission at all -- it is our window receiving our own click.

ClickToTalk implements the same interface as the hotkey capture (a blocking
capture_utterance returning audio or None), so the VoiceSession does not care
which one it is given.
"""
import threading

import numpy as np

from assistant.voice.click import ClickToTalk


class FakeRecorder:
    def __init__(self, sample_rate, frames=None):
        self.sample_rate = sample_rate
        self.buffer = []
        self.started = 0
        self.stopped = 0
        self._frames = frames

    def start(self):
        self.started += 1
        self.buffer = self._frames if self._frames is not None else [
            np.zeros(16000, dtype="float32")
        ]

    def stop(self):
        self.stopped += 1


def _talker(**kw):
    return ClickToTalk(recorder_factory=lambda sr: FakeRecorder(sr), **kw)


def test_records_between_start_and_stop():
    talker = _talker()
    threading.Timer(0.01, talker.stop_listening).start()
    talker.start_listening()
    result = talker.capture_utterance()
    assert result is not None
    audio, sr = result
    assert sr == 16000 and audio.size > 0


def test_capture_waits_until_start_is_pressed():
    """Idle must not record: the microphone opens only on an explicit click."""
    talker = _talker()
    done = threading.Event()

    def run():
        talker.capture_utterance()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    assert not done.wait(0.05), "captured without anyone pressing start"
    talker.start_listening()
    talker.stop_listening()
    assert done.wait(2.0), "did not finish after start+stop"


def test_stop_before_start_does_not_wedge_the_session():
    talker = _talker()
    talker.stop_listening()          # stray click while idle
    threading.Timer(0.01, talker.stop_listening).start()
    talker.start_listening()
    assert talker.capture_utterance() is not None


def test_too_short_a_recording_is_discarded():
    talker = ClickToTalk(
        recorder_factory=lambda sr: FakeRecorder(sr, frames=[np.zeros(10, "float32")]),
        min_seconds=0.3,
    )
    threading.Timer(0.01, talker.stop_listening).start()
    talker.start_listening()
    assert talker.capture_utterance() is None


def test_recorder_is_always_stopped():
    """A microphone left open is worse than a lost utterance."""
    made = []

    def factory(sr):
        r = FakeRecorder(sr)
        made.append(r)
        return r

    talker = ClickToTalk(recorder_factory=factory)
    threading.Timer(0.01, talker.stop_listening).start()
    talker.start_listening()
    talker.capture_utterance()
    assert made and all(r.started == r.stopped for r in made)


def test_reports_whether_it_is_listening():
    """The UI needs this to show state; a silent recorder is the whole problem."""
    talker = _talker()
    assert talker.is_listening is False
    talker.start_listening()
    assert talker.is_listening is True
    talker.stop_listening()
    assert talker.is_listening is False


def test_max_seconds_stops_a_forgotten_session():
    talker = _talker(max_seconds=0.05)
    talker.start_listening()
    assert talker.capture_utterance() is not None, "did not self-stop"
    assert talker.is_listening is False


def test_shutdown_unblocks_a_waiting_capture():
    """Quit must not hang on a capture that is waiting for a click."""
    talker = _talker()
    done = threading.Event()

    def run():
        talker.capture_utterance()
        done.set()

    threading.Thread(target=run, daemon=True).start()
    talker.shutdown()
    assert done.wait(2.0), "capture did not return on shutdown"
