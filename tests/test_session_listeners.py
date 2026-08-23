"""VoiceSession needs a public way to add listeners.

The menu bar, the notifier and the log all want each event. Wiring that by
assigning over session._on_event from outside works until someone renames the
attribute, at which point the menu bar silently stops updating and nothing
fails -- the worst shape of bug for an indicator whose whole job is to show
you what is happening.
"""
import numpy as np

from assistant.voice.session import VoiceSession


class FakeAgent:
    def run(self, text, on_sentence=None):
        return "answer"


class FakePTT:
    def __init__(self):
        self.calls = 0

    def capture_utterance(self):
        self.calls += 1
        return (np.zeros(8000, dtype="float32"), 16000) if self.calls == 1 else None


class FakeSTT:
    def transcribe(self, audio, sr):
        return "hello"


class FakeTTS:
    def speak(self, text):
        pass


def _session(**kw):
    return VoiceSession(FakePTT(), FakeSTT(), FakeAgent(), FakeTTS(), **kw)


def test_ptt_is_reachable_without_touching_a_private():
    ptt = FakePTT()
    session = VoiceSession(ptt, FakeSTT(), FakeAgent(), FakeTTS())
    assert session.ptt is ptt


def test_added_listeners_receive_events():
    seen = []
    session = _session()
    session.add_listener(lambda name, payload: seen.append(name))
    session.run_once()
    assert "transcribed" in seen and "answered" in seen


def test_the_original_on_event_still_fires():
    """Adding a listener must not displace the one passed at construction."""
    original, extra = [], []
    session = _session(on_event=lambda n, p: original.append(n))
    session.add_listener(lambda n, p: extra.append(n))
    session.run_once()
    assert original and extra


def test_a_broken_listener_does_not_silence_the_others():
    good = []

    def boom(name, payload):
        raise RuntimeError("listener exploded")

    session = _session()
    session.add_listener(boom)
    session.add_listener(lambda n, p: good.append(n))
    session.run_once()
    assert good, "one bad listener suppressed the rest"


def test_a_broken_listener_does_not_kill_the_turn():
    def boom(name, payload):
        raise RuntimeError("listener exploded")

    session = _session()
    session.add_listener(boom)
    session.run_once()  # must not raise
