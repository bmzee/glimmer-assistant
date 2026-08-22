from __future__ import annotations

_YES = ("yes", "yeah", "yep", "approve", "confirm", "do it", "go ahead")
_NO = ("no", "nope", "cancel", "stop", "don't", "do not")


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
            if any(word in answer for word in _NO):
                return False
            if any(word in answer for word in _YES):
                return True
            prompt = "Sorry, I did not catch that. Say yes to approve, or no to cancel."
        try:
            self._tts.speak("I'll cancel that.")
        except Exception:
            pass
        return False
