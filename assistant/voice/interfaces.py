from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np


@runtime_checkable
class SpeechToText(Protocol):
    def transcribe(self, audio: "np.ndarray", sample_rate: int) -> str: ...


@runtime_checkable
class TextToSpeech(Protocol):
    def speak(self, text: str) -> None: ...


@runtime_checkable
class PushToTalk(Protocol):
    def capture_utterance(self) -> "tuple[np.ndarray, int] | None": ...
