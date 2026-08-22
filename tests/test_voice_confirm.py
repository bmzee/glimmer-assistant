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


# Regression test for security bug: word-boundary matching prevents false approvals
import pytest


@pytest.mark.parametrize("denial_phrase", [
    "disapprove",
    "i disapprove",
    "never confirm this",
    "won't approve",
    "unapproved",
    "no",
    "no thanks",
    "nope",
    "cancel",
    "stop",
    "do not send it",
    "don't",
    "negative",
    "not now",
])
def test_refusals_are_never_approved(denial_phrase):
    """Explicit refusals must return False, not accidentally match YES substring."""
    confirmer = SpokenConfirmer(ScriptedPTT(), ScriptedSTT([denial_phrase]), RecordingTTS())
    assert confirmer(request()) is False, f"'{denial_phrase}' should not be approved"


@pytest.mark.parametrize("approval_phrase", [
    "yes",
    "yes please",
    "yeah",
    "yep",
    "approve",
    "confirm",
    "do it",
    "go ahead",
    "okay",
])
def test_approvals_require_whole_words(approval_phrase):
    """Approval phrases must match as whole words."""
    confirmer = SpokenConfirmer(ScriptedPTT(), ScriptedSTT([approval_phrase]), RecordingTTS())
    assert confirmer(request()) is True, f"'{approval_phrase}' should be approved"


@pytest.mark.parametrize("unclear_phrase", [
    "yesterday",  # contains "yes" but not as whole word
    "hmm",
    "i know",  # contains "no" but not as whole word
    "what",
])
def test_unclear_phrases_deny_after_attempts(unclear_phrase):
    """Phrases that don't match yes/no/negations should retry and deny after attempts exhausted."""
    confirmer = SpokenConfirmer(
        ScriptedPTT(), ScriptedSTT([unclear_phrase, unclear_phrase]), RecordingTTS(), attempts=2
    )
    assert confirmer(request()) is False, f"'{unclear_phrase}' should be treated as unclear and denied"
