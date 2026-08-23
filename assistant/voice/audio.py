from __future__ import annotations

import threading
import time

import numpy as np


def assemble(frames: list[np.ndarray]) -> np.ndarray:
    if not frames:
        return np.empty(0, dtype="float32")
    return np.concatenate(frames).astype("float32")


class _Recorder:
    """Wraps a sounddevice InputStream, buffering mono float32 frames while open."""

    def __init__(self, sample_rate: int):
        self._sample_rate = sample_rate
        self.buffer: list[np.ndarray] = []
        self._stream = None

    def start(self) -> None:
        import sounddevice

        def callback(indata, frames, time_info, status):
            self.buffer.append(indata[:, 0].copy())

        self._stream = sounddevice.InputStream(
            samplerate=self._sample_rate, channels=1, dtype="float32", callback=callback
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class HotkeyPushToTalk:
    def __init__(
        self,
        hotkey: str = "ctrl",
        sample_rate: int = 16000,
        min_seconds: float = 0.3,
        *,
        recorder_factory=None,
        listener_factory=None,
    ):
        # validate the hotkey names a real modifier/named key
        from pynput import keyboard

        if getattr(keyboard.Key, hotkey, None) is None:
            valid = ", ".join(sorted(k.name for k in keyboard.Key))
            raise ValueError(f"unknown voice_hotkey {hotkey!r}; must be one of: {valid}")

        self._hotkey = hotkey
        self._sample_rate = sample_rate
        self._min_seconds = min_seconds
        self._recorder_factory = recorder_factory or (lambda sr: _Recorder(sr))
        self._listener_factory = listener_factory

    def _run_cycle(self, recorder, wait_for_release) -> "tuple[np.ndarray, int] | None":
        recorder.start()
        try:
            wait_for_release()
        finally:
            recorder.stop()
        audio = assemble(recorder.buffer)
        if audio.size < int(self._min_seconds * self._sample_rate):
            return None
        return audio, self._sample_rate

    def capture_utterance(self) -> "tuple[np.ndarray, int] | None":
        from pynput import keyboard

        released = threading.Event()
        pressed = threading.Event()

        target = getattr(keyboard.Key, self._hotkey, None)

        def on_press(key):
            if key == target:
                pressed.set()

        def on_release(key):
            if key == target and pressed.is_set():
                released.set()
                return False  # stop listener

        recorder = self._recorder_factory(self._sample_rate)
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            pressed.wait()  # block until the hotkey goes down
            return self._run_cycle(recorder, wait_for_release=released.wait)


class DoubleTapToggle:
    """Double-tap to start listening, double-tap again to stop.

    Holding a key for the length of a request is uncomfortable past a sentence
    and competes with typing on a laptop, so this is the hands-free mode.

    A toggle has a failure mode push-to-talk does not: it can be left on.
    Push-to-talk ends when you let go; a toggle ends only when you remember it.
    Hence max_seconds -- a forgotten session stops on its own rather than
    recording until something breaks.
    """

    def __init__(
        self,
        hotkey: str = "alt_r",
        sample_rate: int = 16000,
        min_seconds: float = 0.3,
        *,
        tap_window: float = 0.4,
        max_seconds: float = 120.0,
        recorder_factory=None,
        tap_source=None,
        clock=None,
    ):
        from pynput import keyboard

        if getattr(keyboard.Key, hotkey, None) is None:
            valid = ", ".join(sorted(k.name for k in keyboard.Key))
            raise ValueError(f"unknown voice_hotkey {hotkey!r}; must be one of: {valid}")

        self._hotkey = hotkey
        self._sample_rate = sample_rate
        self._min_seconds = min_seconds
        self._tap_window = tap_window
        self._max_seconds = max_seconds
        self._recorder_factory = recorder_factory or (lambda sr: _Recorder(sr))
        self._tap_source = tap_source
        self._clock = clock or time.monotonic

    def _wait_for_tap(self, timeout=None) -> bool:
        if self._tap_source is not None:
            return self._tap_source(timeout=timeout)
        return self._listen_for_tap(timeout)

    def _listen_for_tap(self, timeout) -> bool:
        from pynput import keyboard

        target = getattr(keyboard.Key, self._hotkey)
        tapped = threading.Event()

        def on_press(key):
            if key == target:
                tapped.set()
                return False

        with keyboard.Listener(on_press=on_press):
            return tapped.wait(timeout)

    def _wait_for_double_tap(self, deadline=None) -> bool:
        """Two taps inside tap_window. A lone tap is not a command.

        Rearms on every tap rather than restarting the pair, so tap-tap-tap
        still registers -- otherwise a nervous third tap would swallow the
        gesture.
        """
        while True:
            remaining = None if deadline is None else deadline - self._clock()
            if remaining is not None and remaining <= 0:
                return False
            if not self._wait_for_tap(timeout=remaining):
                return False
            first = self._clock()
            if not self._wait_for_tap(timeout=self._tap_window):
                continue  # lone tap; keep waiting for a real pair
            if self._clock() - first <= self._tap_window:
                return True

    def capture_utterance(self) -> "tuple[np.ndarray, int] | None":
        if not self._wait_for_double_tap():
            return None

        recorder = self._recorder_factory(self._sample_rate)
        recorder.start()
        try:
            # Stop on a second double-tap, or on the safety deadline, whichever
            # comes first. Never wait forever: the microphone is open.
            self._wait_for_double_tap(deadline=self._clock() + self._max_seconds)
        finally:
            recorder.stop()

        audio = assemble(recorder.buffer)
        if audio.size < int(self._min_seconds * self._sample_rate):
            return None
        return audio, self._sample_rate
