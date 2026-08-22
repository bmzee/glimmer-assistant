import numpy as np

from assistant.security.confirm import ConfirmRequest
from assistant.voice.confirm import SpokenConfirmer


def audio():
    return (np.zeros(8000, dtype="float32"), 16000)


class ScriptedPTT:
    def __init__(self, n=5):
        self._left = n

    def capture_utterance(self):
        if self._left <= 0:
            return None
        self._left -= 1
        return audio()


class ScriptedSTT:
    def __init__(self, replies):
        self._replies = list(replies)

    def transcribe(self, a, sr):
        return self._replies.pop(0) if self._replies else ""


class RecordingTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


def request():
    return ConfirmRequest(tool_name="send_mail", args={"to": "a@b.com"}, preview="send_mail to=a@b.com")


def test_yes_approves():
    tts = RecordingTTS()
    confirmer = SpokenConfirmer(ScriptedPTT(), ScriptedSTT(["yes please"]), tts)
    assert confirmer(request()) is True
    assert any("send_mail" in s for s in tts.spoken)  # preview was spoken


def test_no_denies():
    confirmer = SpokenConfirmer(ScriptedPTT(), ScriptedSTT(["no thanks"]), RecordingTTS())
    assert confirmer(request()) is False


def test_unclear_then_yes_approves():
    confirmer = SpokenConfirmer(ScriptedPTT(), ScriptedSTT(["hmm what", "yes"]), RecordingTTS())
    assert confirmer(request()) is True


def test_unclear_twice_fails_closed():
    confirmer = SpokenConfirmer(
        ScriptedPTT(), ScriptedSTT(["mumble", "more mumble"]), RecordingTTS(), attempts=2
    )
    assert confirmer(request()) is False


def test_capture_error_fails_closed():
    class BoomPTT:
        def capture_utterance(self):
            raise RuntimeError("mic died")

    confirmer = SpokenConfirmer(BoomPTT(), ScriptedSTT(["yes"]), RecordingTTS())
    assert confirmer(request()) is False  # never approve on error


def test_no_utterance_fails_closed():
    class SilentPTT:
        def capture_utterance(self):
            return None

    confirmer = SpokenConfirmer(SilentPTT(), ScriptedSTT([]), RecordingTTS())
    assert confirmer(request()) is False
