"""Capture driven by a click instead of a global hotkey.

The push-to-talk hotkey needs Input Monitoring. macOS gates that permission,
and while it is ungranted the key silently does nothing -- the app runs
perfectly and appears dead, which is the worst failure mode a push-to-talk app
can have.

A button in our own UI needs no permission at all: it is our own window
receiving our own click. This implements the same interface the hotkey capture
does, so VoiceSession neither knows nor cares which it was handed.
"""
from __future__ import annotations

import threading

from assistant.voice.audio import _Recorder, assemble


class ClickToTalk:
    def __init__(
        self,
        sample_rate: int = 16000,
        min_seconds: float = 0.3,
        *,
        max_seconds: float = 120.0,
        recorder_factory=None,
    ):
        self._sample_rate = sample_rate
        self._min_seconds = min_seconds
        self._max_seconds = max_seconds
        self._recorder_factory = recorder_factory or (lambda sr: _Recorder(sr))
        self._start = threading.Event()
        self._stop = threading.Event()
        self._shutdown = threading.Event()
        self._listening = False

    @property
    def is_listening(self) -> bool:
        """The UI shows this. An assistant recording with no visible sign of
        it is precisely the problem this class exists to remove."""
        return self._listening

    def start_listening(self) -> None:
        self._stop.clear()
        self._listening = True
        self._start.set()

    def stop_listening(self) -> None:
        self._listening = False
        self._stop.set()

    def shutdown(self) -> None:
        """Unblock a capture that is waiting, so quitting cannot hang."""
        self._shutdown.set()
        self._start.set()
        self._stop.set()

    def capture_utterance(self) -> "tuple | None":
        # Idle means idle: the microphone opens only on an explicit click.
        while not self._start.wait(timeout=0.2):
            if self._shutdown.is_set():
                return None
        self._start.clear()
        if self._shutdown.is_set():
            return None

        recorder = self._recorder_factory(self._sample_rate)
        recorder.start()
        try:
            # Bounded even if the user forgets: a click-toggle can be left on
            # in a way push-to-talk cannot.
            self._stop.wait(timeout=self._max_seconds)
        finally:
            recorder.stop()
            self._listening = False
            self._stop.clear()

        if self._shutdown.is_set():
            return None
        audio = assemble(recorder.buffer)
        if audio.size < int(self._min_seconds * self._sample_rate):
            return None
        return audio, self._sample_rate
