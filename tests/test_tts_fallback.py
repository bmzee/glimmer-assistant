"""If Kokoro fails, fall back to `say` rather than losing the reply.

The voice session survives a TTS error, but the answer is simply gone -- the
user asked and heard silence, with no indication anything happened. In an app
whose only output channel is audio, a dead synthesiser means a dead app.

macOS `say` is always present, needs no model, and needs no download. It sounds
worse; it is infinitely better than nothing.

Also caps what is spoken. A 36-item directory listing is fine on screen and
unusable aloud, and there is no way to skip or replay.
"""
import pytest

from assistant.voice.tts import SpeakingFailed, SafeTTS, spoken_form


class Boom:
    def __init__(self):
        self.calls = 0

    def speak(self, text):
        self.calls += 1
        raise RuntimeError("onnx exploded")


class Recorder:
    def __init__(self):
        self.said = []

    def speak(self, text):
        self.said.append(text)


def test_uses_the_primary_engine_when_it_works():
    primary, fallback = Recorder(), Recorder()
    SafeTTS(primary, fallback).speak("hello")
    assert primary.said == ["hello"]
    assert fallback.said == [], "fallback used while primary was healthy"


def test_falls_back_when_the_primary_raises():
    primary, fallback = Boom(), Recorder()
    SafeTTS(primary, fallback).speak("hello")
    assert fallback.said == ["hello"], "reply was lost instead of spoken"


def test_stops_retrying_a_dead_primary():
    """Kokoro failing once means it will fail every turn; retrying costs
    seconds of silence before each fallback."""
    primary, fallback = Boom(), Recorder()
    tts = SafeTTS(primary, fallback)
    for _ in range(4):
        tts.speak("hi")
    assert primary.calls == 1, "kept retrying a known-dead engine"
    assert len(fallback.said) == 4


def test_raises_only_when_both_engines_fail():
    """Silence must be reported, not swallowed -- the session logs it."""
    with pytest.raises(SpeakingFailed):
        SafeTTS(Boom(), Boom()).speak("hello")


def test_long_text_is_shortened_for_speech():
    """A 36-item listing is unusable aloud and cannot be skipped or replayed."""
    listing = ", ".join(f"folder{i}" for i in range(40))
    spoken = spoken_form(listing, max_chars=200)
    assert len(spoken) < len(listing)
    assert len(spoken) <= 260  # cap plus the added note


def test_shortened_speech_says_it_was_shortened():
    """Silently truncating makes the assistant sound like it lost track."""
    spoken = spoken_form("x " * 500, max_chars=100)
    assert any(w in spoken.lower() for w in ("shortened", "more", "full", "log"))


def test_short_text_is_untouched():
    assert spoken_form("Hello there.", max_chars=200) == "Hello there."


def test_truncation_falls_on_a_word_boundary():
    spoken = spoken_form("alpha beta gamma delta epsilon zeta", max_chars=20)
    assert not spoken.split("…")[0].rstrip().endswith("gamm")
