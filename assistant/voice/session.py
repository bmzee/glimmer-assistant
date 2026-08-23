from __future__ import annotations

import inspect
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
        self._agent_streams = self._supports_streaming(agent)
        # A list, not a single callback: the log, the notifier and the menu
        # bar all want every event, and each must be isolated -- an indicator
        # that throws must not kill the turn it was reporting on.
        self._listeners = [on_event] if on_event else []

    @property
    def ptt(self):
        """Exposed so a UI can drive start/stop without reaching into privates."""
        return self._ptt

    def add_listener(self, handler) -> None:
        """Add an event listener. Failures in one never affect the others."""
        self._listeners.append(handler)

    def _on_event(self, name, payload) -> None:
        for handler in self._listeners:
            try:
                handler(name, payload)
            except Exception:
                pass  # a broken listener must not take down a working turn

    @staticmethod
    def _supports_streaming(agent) -> bool:
        """Detect on_sentence support once, rather than probing per turn.

        Checked by signature rather than by catching TypeError, so a genuine
        TypeError raised inside the agent is not misread as 'cannot stream'
        and silently downgraded.
        """
        try:
            return "on_sentence" in inspect.signature(agent.run).parameters
        except (TypeError, ValueError):  # builtins/C callables expose no signature
            return False

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
            if self._agent_streams:
                # Speech starts on sentence one, while the model is still
                # writing; the reply is already fully spoken once run returns.
                reply = self._agent.run(transcript, on_sentence=self._tts.speak)
                self._on_event("answered", reply)
            else:
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
