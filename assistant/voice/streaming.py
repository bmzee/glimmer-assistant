from __future__ import annotations

import re

_SENTENCE = re.compile(r"[^.!?]*[.!?]+|\S[^.!?]*$")


def split_sentences(text: str) -> list[str]:
    return [m.group().strip() for m in _SENTENCE.finditer(text) if m.group().strip()]


_TERMINATOR = re.compile(r"[.!?]+")


class SentenceAccumulator:
    """Splits a stream of token deltas into speakable sentences.

    ``split_sentences`` needs the finished answer, so nothing can be spoken
    until generation completes -- the dominant term in the spec SS9 latency
    budget. This releases each sentence as soon as its terminator arrives, so
    TTS can start on sentence one while the model is still writing.

    ``min_chars`` coalesces short fragments. The splitter treats every '.' as
    a terminator, so a streamed "Dr. Smith replied." would otherwise become
    two separate TTS calls, and a lone "Dr." sounds broken when spoken.
    """

    def __init__(self, min_chars: int = 0):
        self._min_chars = min_chars
        self._buffer = ""   # text seen but not yet forming a complete sentence
        self._pending = ""  # complete sentences held back for being too short
        self._text = ""     # everything fed, for the caller's own bookkeeping

    def feed(self, delta: str) -> list[str]:
        self._text += delta
        self._buffer += delta
        released: list[str] = []
        while True:
            match = _TERMINATOR.search(self._buffer)
            if match is None:
                break
            sentence = self._buffer[: match.end()].strip()
            self._buffer = self._buffer[match.end() :]
            if not sentence:
                continue
            self._pending = f"{self._pending} {sentence}".strip() if self._pending else sentence
            if len(self._pending) >= self._min_chars:
                released.append(self._pending)
                self._pending = ""
        return released

    def flush(self) -> list[str]:
        """Release whatever is left, terminated or not."""
        tail = f"{self._pending} {self._buffer.strip()}".strip()
        self._pending = ""
        self._buffer = ""
        return [tail] if tail else []

    def text(self) -> str:
        return self._text.strip()
