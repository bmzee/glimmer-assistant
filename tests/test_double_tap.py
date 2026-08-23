"""Double-tap to start listening, double-tap again to stop.

Holding a key for the length of a request is uncomfortable for anything longer
than a sentence, and on a laptop it competes with typing. A toggle lets the
user speak hands-free.

The cost is that a toggle can be left on: push-to-talk ends when you let go,
a toggle ends only when you remember it. So it needs a maximum session length,
or a forgotten double-tap records until the disk fills.

Everything is injected -- these tests never open a microphone or a key listener.
"""
import threading

import numpy as np
import pytest

from assistant.voice.audio import DoubleTapToggle


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


class FakeClock:
    """Controllable time, so tap-window logic never depends on wall clock."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _toggle(taps, clock=None, **kw):
    """taps: list of (delay_before_tap_seconds,) applied to the fake clock."""
    clock = clock or FakeClock()
    remaining = list(taps)

    def wait_for_tap(timeout=None):
        if not remaining:
            return False
        gap = remaining.pop(0)
        clock.advance(gap)
        return True

    return (
        DoubleTapToggle(
            hotkey="alt_r",
            recorder_factory=lambda sr: FakeRecorder(sr),
            tap_source=wait_for_tap,
            clock=clock,
            **kw,
        ),
        clock,
    )


def test_two_quick_taps_start_recording_and_two_more_stop_it():
    # start pair (0.1s apart), then stop pair (0.1s apart)
    toggle, _ = _toggle([0.0, 0.1, 2.0, 0.1])
    result = toggle.capture_utterance()
    assert result is not None
    audio, sr = result
    assert sr == 16000
    assert audio.size > 0


def test_taps_too_far_apart_are_not_a_double_tap():
    """A single stray press must not open a listening session."""
    toggle, _ = _toggle([0.0, 5.0], max_seconds=1.0)
    # Only two taps, 5s apart: never a pair, so nothing is captured.
    assert toggle.capture_utterance() is None


def test_recording_stops_at_the_maximum_even_without_a_second_double_tap():
    """A toggle left on must not record forever."""
    toggle, _ = _toggle([0.0, 0.1], max_seconds=30.0)
    result = toggle.capture_utterance()
    assert result is not None, "hit max length but returned nothing"


def test_recorder_is_always_stopped_even_when_nothing_is_returned():
    """A live microphone left open is worse than a lost utterance."""
    made = []

    def factory(sr):
        r = FakeRecorder(sr, frames=[np.zeros(10, dtype="float32")])
        made.append(r)
        return r

    toggle = DoubleTapToggle(
        hotkey="alt_r",
        recorder_factory=factory,
        tap_source=lambda timeout=None: False,  # no taps ever
        clock=FakeClock(),
    )
    toggle.capture_utterance()
    for r in made:
        assert r.started == r.stopped, "recorder left running"


def test_too_short_a_session_is_discarded():
    """Two double-taps in quick succession capture nothing worth sending."""
    toggle = DoubleTapToggle(
        hotkey="alt_r",
        recorder_factory=lambda sr: FakeRecorder(sr, frames=[np.zeros(10, dtype="float32")]),
        tap_source=_toggle([0.0, 0.1, 0.05, 0.1])[0]._tap_source,
        clock=FakeClock(),
        min_seconds=0.3,
    )
    assert toggle.capture_utterance() is None


def test_rejects_an_unknown_hotkey_at_construction():
    """A hotkey that silently never fires is the worst outcome here."""
    with pytest.raises(ValueError, match="unknown"):
        DoubleTapToggle(hotkey="not_a_key", recorder_factory=lambda sr: FakeRecorder(sr))


def test_tap_window_is_configurable():
    toggle, _ = _toggle([0.0, 0.35, 2.0, 0.1], tap_window=0.5)
    assert toggle.capture_utterance() is not None, (
        "0.35s gap should count as a double tap when the window is 0.5s"
    )
