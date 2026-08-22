from __future__ import annotations

import threading

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
