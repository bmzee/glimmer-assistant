"""Hands-free capture: an utterance is bounded by speech, not by clicks.

Click-speak-click is worse than a hotkey, and it existed only because the
hotkey needed a permission macOS would not grant. Listening continuously
removes the interaction entirely: start talking and it hears you, stop talking
and it answers.

The hard part is not detecting speech but deciding when you have FINISHED.
Cutting on the first quiet frame truncates anyone who pauses to think; waiting
too long makes every reply feel laggy. So the end of an utterance is a *run* of
silence, and a short pause mid-sentence is kept as part of one request.
"""
from __future__ import annotations

import threading
import time

from assistant.voice.audio import _Recorder, assemble, rms_level


class VoiceActivityCapture:
    def __init__(
        self,
        sample_rate: int = 16000,
        min_seconds: float = 0.4,
        *,
        speech_level: float = 0.06,
        silence_seconds: float = 0.9,
        max_seconds: float = 30.0,
        frame_seconds: float = 0.1,
        recorder_factory=None,
        pump=None,
    ):
        self._sample_rate = sample_rate
        self._min_seconds = min_seconds
        self._speech_level = speech_level
        self._silence_seconds = silence_seconds
        self._max_seconds = max_seconds
        self._frame_seconds = frame_seconds
        self._recorder_factory = recorder_factory or (lambda sr: _Recorder(sr))
        # Injected in tests so timing is deterministic and no microphone opens.
        self._pump = pump
        self._shutdown = threading.Event()
        self._listening = False
        self._recorder = None

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def level(self) -> float:
        rec = self._recorder
        if rec is None:
            return 0.0
        try:
            return rms_level(rec.buffer)
        except Exception:
            return 0.0

    # Present so the UI can drive it like the click capture; with VAD the
    # microphone is always open, so these are no-ops rather than errors.
    def start_listening(self) -> None:
        return None

    def stop_listening(self) -> None:
        return None

    def shutdown(self) -> None:
        self._shutdown.set()

    def _wait_frame(self) -> bool:
        if self._pump is not None:
            return self._pump()
        time.sleep(self._frame_seconds)
        return True

    def capture_utterance(self):
        if self._shutdown.is_set():
            return None

        recorder = self._recorder_factory(self._sample_rate)
        self._recorder = recorder
        recorder.start()
        self._listening = True

        frames_per_second = 1.0 / self._frame_seconds
        silence_needed = int(self._silence_seconds * frames_per_second)
        max_frames = int(self._max_seconds * frames_per_second)

        speech_start = None      # index of the first frame containing speech
        last_loud = None         # index of the LAST frame containing speech
        silent_run = 0
        seen = 0

        try:
            while not self._shutdown.is_set():
                if not self._wait_frame():
                    break
                buf = recorder.buffer
                if len(buf) <= seen:
                    continue
                seen = len(buf)

                # Judge only the newest frame: an average over the whole buffer
                # would be dragged down by leading silence and never trip.
                loud = rms_level(buf[-1:], window_frames=1) >= self._speech_level

                if loud:
                    if speech_start is None:
                        speech_start = seen - 1
                    last_loud = seen - 1
                    silent_run = 0
                elif speech_start is not None:
                    silent_run += 1
                    if silent_run >= silence_needed:
                        break

                if speech_start is not None and (seen - speech_start) >= max_frames:
                    break
        finally:
            recorder.stop()
            self._listening = False
            self._recorder = None

        if self._shutdown.is_set() or speech_start is None:
            return None

        # Keep one frame of lead-in and a short tail, then DROP the rest of
        # the trailing silence. Two reasons: the minimum-length check must
        # measure speech rather than padding (otherwise one loud frame plus a
        # second of room tone passes as an utterance), and Parakeet transcribes
        # noticeably worse when handed a long run of near-silence.
        start = max(0, speech_start - 1)
        end = (last_loud + 2) if last_loud is not None else len(recorder.buffer)
        audio = assemble(recorder.buffer[start:end])
        if audio.size < int(self._min_seconds * self._sample_rate):
            return None
        return audio, self._sample_rate
