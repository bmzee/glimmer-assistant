from __future__ import annotations

import time
from typing import Callable

from assistant.voice.streaming import split_sentences

_ERROR_SPEECH = "Sorry, something went wrong."


class VoiceSession:
    def __init__(
        self,
        ptt,
        stt,
        agent,
        tts,
        min_utterance_seconds: float = 0.3,
        on_event: Callable[[str, object], None] | None = None,
    ):
        self._ptt = ptt
        self._stt = stt
        self._agent = agent
        self._tts = tts
        self._min_seconds = min_utterance_seconds
        self._on_event = on_event or (lambda name, payload: None)

    def run_once(self) -> None:
        self._on_event("listening", None)
        try:
            captured = self._ptt.capture_utterance()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            self._on_event("error", e)
            time.sleep(0.5)  # avoid a tight error loop on a permanent device failure
            return
        if captured is None:
            return
        audio, sample_rate = captured
        try:
            transcript = self._stt.transcribe(audio, sample_rate).strip()
            if not transcript:
                return
            self._on_event("transcribed", transcript)
            reply = self._agent.run(transcript)
            self._on_event("answered", reply)
            for sentence in split_sentences(reply):
                self._tts.speak(sentence)
        except Exception as e:  # a bad turn must not kill the session
            self._on_event("error", e)
            try:
                self._tts.speak(_ERROR_SPEECH)
            except Exception:
                pass  # TTS itself may be the failure; never let recovery crash the loop

    def run_forever(self) -> None:
        try:
            while True:
                self.run_once()
        except KeyboardInterrupt:
            return
