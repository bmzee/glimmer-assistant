from __future__ import annotations

import re

_YES = ("yes", "yeah", "yep", "yup", "approve", "confirm", "do it", "go ahead", "send it", "okay", "ok")
_NO = ("no", "nope", "cancel", "stop", "don't", "dont", "do not", "negative")
# Negations that would otherwise leave a YES word intact ("never confirm", "won't approve")
_NEGATIONS = ("never", "won't", "wont", "cannot", "can't", "cant", "not", "disapprove", "disapproved", "unapproved", "abort")


def _matches(answer: str, phrases) -> bool:
    """Check if any phrase matches as a whole word in answer."""
    return any(re.search(r"\b" + re.escape(p) + r"\b", answer) for p in phrases)


class SpokenConfirmer:
    """Asks the user to approve a Tier-2 action by voice. Fails closed."""

    def __init__(self, ptt, stt, tts, *, attempts: int = 2):
        self._ptt = ptt
        self._stt = stt
        self._tts = tts
        self._attempts = attempts

    def __call__(self, request) -> bool:
        prompt = f"{request.preview}. Say yes to approve, or no to cancel."
        for _ in range(self._attempts):
            try:
                self._tts.speak(prompt)
                captured = self._ptt.capture_utterance()
                if captured is None:
                    continue
                audio, sample_rate = captured
                answer = self._stt.transcribe(audio, sample_rate).strip().lower()
            except Exception:
                return False  # fail closed on any error
            if _matches(answer, _NO) or _matches(answer, _NEGATIONS):
                return False
            if _matches(answer, _YES):
                return True
            prompt = "Sorry, I did not catch that. Say yes to approve, or no to cancel."
        try:
            self._tts.speak("I'll cancel that.")
        except Exception:
            pass
        return False
