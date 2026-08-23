"""Say something immediately, because the real wait is 15-24 seconds.

Measured time to first spoken word on real turns: 14.5s (one tool) to 23.9s
(no tool). Streaming does not help -- this model emits ALL its reasoning
tokens before any content, so there is nothing to stream until thinking ends.
Suppressing reasoning was measured and rejected (10/10 -> 9/10, and </think>
leaking into speech).

That leaves acknowledging. It does not make the answer faster; it makes the
silence stop being silence, which is the difference between "thinking" and
"broken" from the user's side.
"""
from assistant.voice.acknowledge import acknowledgement_for, should_acknowledge


def test_produces_something_to_say():
    assert acknowledgement_for("what is on my desktop").strip()


def test_acknowledgement_is_short():
    """It is spoken before the answer; a long one delays what you asked for."""
    for prompt in ("open chrome", "what is on my desktop", "read my mail"):
        assert len(acknowledgement_for(prompt)) <= 30


def test_varies_so_it_does_not_feel_robotic():
    seen = {acknowledgement_for(f"request number {i}") for i in range(40)}
    assert len(seen) > 1, "same phrase every turn is worse than none"


def test_is_deterministic_for_the_same_input():
    """Stable output keeps this testable and avoids surprising the user."""
    assert acknowledgement_for("open chrome") == acknowledgement_for("open chrome")


def test_skipped_when_the_answer_will_be_fast_anyway():
    """Acknowledging a sub-second reply just doubles the talking."""
    assert should_acknowledge(expected_seconds=0.5) is False
    assert should_acknowledge(expected_seconds=15.0) is True


def test_empty_transcript_is_not_acknowledged():
    assert acknowledgement_for("") == ""


def test_never_promises_a_particular_answer():
    """A filler that says "opening it now" is a lie when the tool then fails."""
    for i in range(40):
        phrase = acknowledgement_for(f"req {i}").lower()
        assert "open" not in phrase and "done" not in phrase


def test_session_speaks_a_filler_before_the_answer_when_enabled():
    """Wired through the real VoiceSession, not just the phrase picker."""
    import numpy as np

    from assistant.voice.session import VoiceSession

    class PTT:
        def __init__(self):
            self.n = 0

        def capture_utterance(self):
            self.n += 1
            return (np.zeros(8000, dtype="float32"), 16000) if self.n == 1 else None

    class STT:
        def transcribe(self, a, sr):
            return "what is on my desktop"

    class Agent:
        """Advertises streaming AND actually streams. A fake that accepts
        on_sentence but never calls it takes the streaming path and then
        speaks nothing, which is a bug in the fake, not the session."""

        def run(self, text, on_sentence=None):
            if on_sentence:
                on_sentence("Three files.")
            return "Three files."

    class TTS:
        def __init__(self):
            self.spoken = []

        def speak(self, t):
            self.spoken.append(t)

    tts = TTS()
    VoiceSession(PTT(), STT(), Agent(), tts, acknowledge=True).run_once()
    assert len(tts.spoken) >= 2, "no filler spoken"
    assert tts.spoken[-1] == "Three files.", "the real answer must still arrive"

    quiet = TTS()
    VoiceSession(PTT(), STT(), Agent(), quiet, acknowledge=False).run_once()
    assert quiet.spoken == ["Three files."], "filler leaked into the default path"
