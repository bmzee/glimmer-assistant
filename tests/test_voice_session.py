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
