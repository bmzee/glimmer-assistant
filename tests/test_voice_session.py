import numpy as np

from assistant.voice.session import VoiceSession


class FakePTT:
    def __init__(self, utterances):
        self._utterances = list(utterances)

    def capture_utterance(self):
        return self._utterances.pop(0)


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def transcribe(self, audio, sample_rate):
        self.calls.append((audio, sample_rate))
        return self.text


class FakeAgent:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def run(self, text):
        self.prompts.append(text)
        return self.reply


class FakeTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


def audio():
    return (np.zeros(8000, dtype="float32"), 16000)


def test_full_utterance_flow():
    ptt = FakePTT([audio()])
    stt = FakeSTT("what is on my desktop")
    agent = FakeAgent("You have three files. They are small.")
    tts = FakeTTS()
    session = VoiceSession(ptt, stt, agent, tts)

    session.run_once()

    assert stt.calls[0][1] == 16000
    assert agent.prompts == ["what is on my desktop"]
    # answer spoken sentence-by-sentence
    assert tts.spoken == ["You have three files.", "They are small."]


def test_none_utterance_is_ignored():
    ptt = FakePTT([None])
    stt = FakeSTT("unused")
    agent = FakeAgent("unused")
    tts = FakeTTS()
    session = VoiceSession(ptt, stt, agent, tts)

    session.run_once()

    assert agent.prompts == []
    assert tts.spoken == []


def test_blank_transcript_skips_agent():
    ptt = FakePTT([audio()])
    session = VoiceSession(ptt, FakeSTT("   "), FakeAgent("x"), FakeTTS())
    session.run_once()
    # agent never called on empty transcription
    assert session._agent.prompts == []


def test_agent_error_is_spoken_not_raised():
    class BoomAgent:
        def run(self, text):
            raise RuntimeError("kaboom")

    ptt = FakePTT([audio()])
    tts = FakeTTS()
    session = VoiceSession(ptt, FakeSTT("hi"), BoomAgent(), tts)

    session.run_once()  # must not raise

    assert any("something went wrong" in s.lower() for s in tts.spoken)


def test_run_forever_stops_on_keyboard_interrupt():
    class InterruptingPTT:
        def capture_utterance(self):
            raise KeyboardInterrupt

    session = VoiceSession(InterruptingPTT(), FakeSTT("x"), FakeAgent("y"), FakeTTS())
    session.run_forever()  # returns cleanly, does not propagate


def test_tts_failure_does_not_crash_session():
    class BoomTTS:
        def speak(self, text):
            raise RuntimeError("audio dead")

    ptt = FakePTT([audio()])
    stt = FakeSTT("hello")
    agent = FakeAgent("Good morning.")
    tts = BoomTTS()
    session = VoiceSession(ptt, stt, agent, tts)

    session.run_once()  # must not raise, even though both reply-speak and recovery-speak fail


def test_capture_error_does_not_crash_and_is_reported(monkeypatch):
    from assistant.voice import session as session_module

    monkeypatch.setattr(session_module.time, "sleep", lambda *_args, **_kwargs: None)

    class BoomPTT:
        def capture_utterance(self):
            raise RuntimeError("device gone")

    events = []
    session = VoiceSession(
        BoomPTT(),
        FakeSTT("unused"),
        FakeAgent("unused"),
        FakeTTS(),
        on_event=lambda name, payload: events.append((name, payload)),
    )

    session.run_once()  # must not raise

    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) == 1
    assert isinstance(error_events[0][1], RuntimeError)
    assert str(error_events[0][1]) == "device gone"


def test_capture_keyboardinterrupt_still_propagates_via_run_forever():
    class InterruptingPTT:
        def capture_utterance(self):
            raise KeyboardInterrupt

    session = VoiceSession(InterruptingPTT(), FakeSTT("x"), FakeAgent("y"), FakeTTS())
    session.run_forever()  # returns cleanly, does not hang or raise


def test_stt_failure_is_spoken_not_raised():
    class BoomSTT:
        def transcribe(self, audio, sample_rate):
            raise RuntimeError("mic broken")

    ptt = FakePTT([audio()])
    stt = BoomSTT()
    agent = FakeAgent("unused")
    tts = FakeTTS()
    session = VoiceSession(ptt, stt, agent, tts)

    session.run_once()  # must not raise

    # error message was spoken (recovery succeeded with working TTS)
    assert any("something went wrong" in s.lower() for s in tts.spoken)


# --- streaming: speak sentences as the agent produces them -------------------
#
# The session previously waited for the complete answer before speaking any of
# it, which is the dominant term in the spec SS9 latency gate (docs/latency.md).
# When the agent supports on_sentence, the session hands TTS each sentence as
# it is produced. Agents that do not support it must keep working unchanged.


class StreamingFakeAgent:
    """Emits sentences through on_sentence, like the real AgentLoop."""

    def __init__(self, sentences):
        self.sentences = sentences
        self.streamed = False

    def run(self, text, on_sentence=None):
        if on_sentence is not None:
            self.streamed = True
            for s in self.sentences:
                on_sentence(s)
        return " ".join(self.sentences)


def test_streams_sentences_to_tts_when_the_agent_supports_it():
    ptt = FakePTT([audio()])
    agent = StreamingFakeAgent(["First part.", "Second part."])
    tts = FakeTTS()
    session = VoiceSession(ptt, FakeSTT("hello"), agent, tts)

    session.run_once()

    assert agent.streamed is True
    assert tts.spoken == ["First part.", "Second part."]


def test_speech_begins_before_the_agent_returns():
    """Fails on any implementation that waits for the full reply."""
    order = []

    class SlowTailAgent:
        def run(self, text, on_sentence=None):
            on_sentence("Ready.")
            order.append("agent-still-working")
            return "Ready. And the rest."

    class RecordingTTS:
        def speak(self, text):
            order.append(f"spoke:{text}")

    session = VoiceSession(FakePTT([audio()]), FakeSTT("hi"), SlowTailAgent(),
                           RecordingTTS())
    session.run_once()

    assert order.index("spoke:Ready.") < order.index("agent-still-working")


def test_non_streaming_agent_still_works():
    """Duck-typed agents without on_sentence must not break the session."""
    ptt = FakePTT([audio()])
    agent = FakeAgent("Alpha. Beta.")
    tts = FakeTTS()
    session = VoiceSession(ptt, FakeSTT("hi"), agent, tts)

    session.run_once()

    assert tts.spoken == ["Alpha.", "Beta."]


def test_streaming_reply_is_not_spoken_twice():
    """Guards the obvious bug: stream the sentences AND re-split the reply."""
    ptt = FakePTT([audio()])
    agent = StreamingFakeAgent(["Only once."])
    tts = FakeTTS()
    session = VoiceSession(ptt, FakeSTT("hi"), agent, tts)

    session.run_once()

    assert tts.spoken == ["Only once."]
